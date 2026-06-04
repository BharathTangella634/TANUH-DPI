"""
common/metrics.py — Shared Prometheus metric definitions for the DPI platform.

All metrics use the `dpi_` prefix. Labels are kept intentionally low-cardinality:
  - `service`: one of the known DPI service names (5 values max)
  - `method`:  HTTP verb (GET/POST — 2 values)
  - `status_code`: HTTP status as string ("200", "422", "500" etc — ~10 distinct values)

Forbidden labels (never added): request_id, user_id, email, token,
document_name, file_name, job_id, task_id, ip_address.

Import pattern (in each service):
    from common.metrics import (
        HTTP_REQUESTS_TOTAL,
        HTTP_REQUEST_DURATION_SECONDS,
        HTTP_REQUEST_FAILURES_TOTAL,
        TASKS_STARTED_TOTAL,
        TASKS_COMPLETED_TOTAL,
        TASKS_FAILED_TOTAL,
        TASK_DURATION_SECONDS,
        DOCUMENTS_PROCESSED_TOTAL,
        DOCUMENTS_FAILED_TOTAL,
        instrument_fastapi,
    )
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

# ── API Metrics ───────────────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "dpi_http_requests_total",
    "Total HTTP requests received by a DPI API service.",
    ["service", "method", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "dpi_http_request_duration_seconds",
    "HTTP request latency in seconds for DPI API services.",
    ["service", "method"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

HTTP_REQUEST_FAILURES_TOTAL = Counter(
    "dpi_http_request_failures_total",
    "Total HTTP requests that resulted in a 5xx error.",
    ["service"],
)

# ── Worker / Task Metrics ─────────────────────────────────────────────────────

TASKS_STARTED_TOTAL = Counter(
    "dpi_tasks_started_total",
    "Total Celery tasks started.",
    ["service"],
)

TASKS_COMPLETED_TOTAL = Counter(
    "dpi_tasks_completed_total",
    "Total Celery tasks that completed successfully.",
    ["service"],
)

TASKS_FAILED_TOTAL = Counter(
    "dpi_tasks_failed_total",
    "Total Celery tasks that raised an unhandled exception.",
    ["service"],
)

TASK_DURATION_SECONDS = Histogram(
    "dpi_task_duration_seconds",
    "End-to-end wall-clock duration of a Celery task in seconds.",
    ["service"],
    buckets=[5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0],
)

# ── Business / Document Metrics ───────────────────────────────────────────────

DOCUMENTS_PROCESSED_TOTAL = Counter(
    "dpi_documents_processed_total",
    "Total documents that completed the full processing pipeline successfully.",
    ["service"],
)

DOCUMENTS_FAILED_TOTAL = Counter(
    "dpi_documents_failed_total",
    "Total documents that failed processing (pipeline or task error).",
    ["service"],
)

# ── Queue Depth Gauges (set by the queue-metrics exporter) ───────────────────

QUEUE_DEPTH = Gauge(
    "dpi_queue_depth",
    "Current number of messages waiting in a Celery/Redis queue.",
    ["queue"],
)

# ── FastAPI middleware helper ─────────────────────────────────────────────────

import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class _MetricsMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that records dpi_http_* metrics for every request.

    Excluded paths: /metrics, /health, /*/health  — these are internal probes
    and would inflate request counts without operational value.
    """

    _EXCLUDED_PREFIXES = ("/metrics", "/health", "/api/health")

    def __init__(self, app: ASGIApp, service: str) -> None:
        super().__init__(app)
        self._service = service

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip internal probe paths to avoid noise in counters
        if any(path == p or path.startswith(p + "/") for p in self._EXCLUDED_PREFIXES):
            return await call_next(request)

        method = request.method
        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            HTTP_REQUEST_FAILURES_TOTAL.labels(service=self._service).inc()
            raise
        finally:
            duration = time.perf_counter() - start
            status_str = str(status_code)
            HTTP_REQUESTS_TOTAL.labels(
                service=self._service,
                method=method,
                status_code=status_str,
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                service=self._service,
                method=method,
            ).observe(duration)
            if status_code >= 500:
                HTTP_REQUEST_FAILURES_TOTAL.labels(service=self._service).inc()


def instrument_fastapi(app, service: str) -> None:
    """
    Attach Prometheus middleware and a /metrics endpoint to a FastAPI app.

    Usage:
        from common.metrics import instrument_fastapi
        instrument_fastapi(app, service="pdf2abdm")
    """
    from fastapi import FastAPI
    from prometheus_client import make_asgi_app, CONTENT_TYPE_LATEST, generate_latest
    from fastapi.responses import Response

    # Attach middleware
    app.add_middleware(_MetricsMiddleware, service=service)

    # Expose /metrics endpoint
    metrics_app = make_asgi_app()

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )
