import os
import time
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
import redis
from prometheus_client import Counter, REGISTRY

logger = logging.getLogger("common.rate_limit")

# ── Safe Prometheus Metrics Registry Helper ──────────────────────────────────
def _get_or_create_counter(name: str, documentation: str, labelnames=()) -> Counter:
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Counter(name, documentation, labelnames=labelnames)


DPI_TOKENS_GENERATED_TOTAL = _get_or_create_counter(
    "dpi_tokens_generated_total",
    "Total number of developer tokens successfully generated",
    labelnames=["service"]
)
DPI_EXISTING_TOKEN_RETURNED_TOTAL = _get_or_create_counter(
    "dpi_existing_token_returned_total",
    "Total number of cached developer tokens returned",
    labelnames=["service"]
)
DPI_AUTH_FAILURES_TOTAL = _get_or_create_counter(
    "dpi_auth_failures_total",
    "Total number of authentication failures",
    labelnames=["service", "failure_type"]
)
DPI_UNAUTHORIZED_REQUESTS_TOTAL = _get_or_create_counter(
    "dpi_unauthorized_requests_total",
    "Total number of unauthorized requests",
    labelnames=["service"]
)
DPI_RATE_LIMIT_EXCEEDED_TOTAL = _get_or_create_counter(
    "dpi_rate_limit_exceeded_total",
    "Total number of requests blocked by rate limiting",
    labelnames=["service"]
)


# ── Request ID Middleware ───────────────────────────────────────────────────
class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates a unique UUID request_id for each incoming request,
    attaching it to `request.state.request_id` and injecting `X-Request-ID` in response headers.
    """
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ── Standardized Exception / Error Handling Register ─────────────────────────
def register_standard_error_handlers(app):
    """
    Registers global exception handlers on a FastAPI application to ensure all 
    errors return the standardized production-grade format:
    {
       "detail": "...",
       "code": "...",
       "request_id": "...",
       "timestamp": "..."
    }
    """
    @app.exception_handler(HTTPException)
    async def standard_http_exception_handler(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", "unknown")
        # Record metric if auth-related
        if exc.status_code == 401:
            DPI_AUTH_FAILURES_TOTAL.labels(service=app.title, failure_type="unauthorized").inc()
        elif exc.status_code == 403:
            DPI_UNAUTHORIZED_REQUESTS_TOTAL.labels(service=app.title).inc()

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "code": f"HTTP_{exc.status_code}",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    @app.exception_handler(RequestValidationError)
    async def standard_validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc.errors()),
                "code": "VALIDATION_ERROR",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

    @app.exception_handler(Exception)
    async def standard_generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception(f"Unhandled Exception [request_id={request_id}]: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred.",
                "code": "INTERNAL_SERVER_ERROR",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )


# ── Rate Limiting Middleware ─────────────────────────────────────────────────
class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Production-grade distributed sliding-window rate limiting middleware using Redis.
    - Limits requests to 150 requests per minute (RPM) per developer token.
    - Key concerns are isolated; executes BEFORE authentication (fail-open if Redis is down).
    - Excludes health checks, metrics, and documentation routes.
    - Emits clean, structured, non-plaintext audit logs (<2ms overhead).
    """
    def __init__(self, app, service_name: str, limit: int = 150, period: int = 60):
        super().__init__(app)
        self.service_name = service_name
        self.limit = limit
        self.period = period
        self.redis_client = None

    def _get_redis(self) -> redis.Redis:
        if self.redis_client is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.redis_client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0
            )
        return self.redis_client

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        request_id = getattr(request.state, "request_id", "unknown")

        # 1. Bypass non-inference public endpoints
        bypassed_keywords = ["/health", "/model-health", "/ocr-health", "/metrics", "/docs", "/openapi.json"]
        if any(path.endswith(k) or k in path for k in bypassed_keywords) or path == "/":
            return await call_next(request)

        # 2. Scope rate limiting to POST processing/splicing/submitting or polling endpoints
        protected_keywords = ["submit", "jobs", "results", "task-status", "task-result", "redact", "apply-redactions", "pdf2abdm", "pdf2nhcx"]
        is_expensive_route = any(k in path for k in protected_keywords) or request.method == "POST"

        if not is_expensive_route:
            return await call_next(request)

        # 3. Extract the Bearer token to identify the client
        auth_header = request.headers.get("Authorization", "")
        token_hash = "anonymous"
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Build isolated key per token (or IP if unauthenticated client-bypass)
        identifier = token_hash
        if identifier == "anonymous":
            client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
            identifier = f"ip:{client_ip}"

        key = f"rate_limit:{self.service_name}:{identifier}"
        now = time.time()

        try:
            r = self._get_redis()
            
            # Atomic sliding-window pipeline
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - self.period)
            pipe.zcard(key)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.expire(key, self.period + 10)
            
            _, current_count, _, _ = pipe.execute()

            if current_count > self.limit:
                # Increment metrics
                DPI_RATE_LIMIT_EXCEEDED_TOTAL.labels(service=self.service_name).inc()

                # Throttled! Read oldest timestamp to compute exact Retry-After
                oldest_score = r.zrange(key, 0, 0, withscores=True)
                retry_after = self.period
                if oldest_score:
                    retry_after = max(1, int(oldest_score[0][1] + self.period - now))

                logger.warning(
                    f"rate_limit_exceeded: service={self.service_name} token_hash={token_hash[:12]} "
                    f"endpoint={path} count={current_count} retry_after={retry_after}s request_id={request_id}"
                )

                response = JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Maximum allowed: {self.limit} requests per minute.",
                        "code": "RATE_LIMIT_EXCEEDED",
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
                response.headers["Retry-After"] = str(retry_after)
                return response

            # Request allowed under window limits
            logger.info(
                f"rate_limit_allowed: service={self.service_name} token_hash={token_hash[:12]} "
                f"endpoint={path} count={current_count} request_id={request_id}"
            )

        except Exception as exc:
            # FAILURE POLICY: Fail Open to protect service availability
            logger.warning(
                f"redis_unavailable: service={self.service_name} token_hash={token_hash[:12]} "
                f"endpoint={path} error={exc} request_id={request_id}. Rate limiting bypassed (fail-open)."
            )

        return await call_next(request)
