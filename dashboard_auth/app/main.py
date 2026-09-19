"""
dashboard_auth — FastAPI microservice (port 8005)
==================================================
Minimal login gate for the internal ops dashboard at dpi.tanuh.ai/admin-dashboard.

This service does not talk to Grafana at all. Grafana is reachable behind the
same reverse proxy as an anonymous Viewer (see monitoring/monitoring/docker-compose
.monitoring.yml) — the only thing this service protects is whether the static
shell (frontend/admin-dashboard/dashboard.html) renders the dashboard tabs or
redirects to the login page. The credential is a single shared admin account,
not a real user-management system — it is meant to be replaced with proper
SSO/OIDC before this stays public long-term.

Endpoints:
  POST /admin-dashboard/api/login    — checks username/password, sets session cookie
  GET  /admin-dashboard/api/session  — reports whether the request has a valid session
  POST /admin-dashboard/api/logout   — clears the session cookie
  GET  /admin-dashboard/api/health   — liveness probe
"""

import hmac
import time
import base64
import hashlib
import logging
import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard_auth")

ADMIN_USERNAME = os.getenv("ADMIN_DASHBOARD_USERNAME", "Admin")
ADMIN_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "Admin@TANUH_12345!")
SECRET_KEY = os.getenv("ADMIN_DASHBOARD_SECRET_KEY", "dev-change-me-in-production").encode()

COOKIE_NAME = "dpi_admin_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours

# ── Brute-force guard ─────────────────────────────────────────────────────────
# In-memory only (single-process service, no shared state needed): after
# MAX_ATTEMPTS failed logins from one IP, lock that IP out for LOCKOUT_SECONDS.
# This is a stopgap for the "temporarily public, single shared password" window
# — not a substitute for real auth, which is planned as a follow-up.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
_failed_attempts: dict[str, tuple[int, float]] = {}  # ip -> (count, locked_until_epoch)

app = FastAPI(title="dashboard-auth", docs_url=None, redoc_url=None)


def _sign(payload: str) -> str:
    sig = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _make_token(username: str) -> str:
    expiry = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}:{expiry}"
    return f"{payload}:{_sign(payload)}"


def _verify_token(token: str) -> bool:
    try:
        username, expiry_str, sig = token.rsplit(":", 2)
        payload = f"{username}:{expiry_str}"
        if not hmac.compare_digest(_sign(payload), sig):
            return False
        return int(expiry_str) > int(time.time())
    except (ValueError, TypeError):
        return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_locked_out(ip: str) -> bool:
    count, locked_until = _failed_attempts.get(ip, (0, 0.0))
    return count >= MAX_ATTEMPTS and time.time() < locked_until


def _record_failure(ip: str) -> None:
    count, _ = _failed_attempts.get(ip, (0, 0.0))
    count += 1
    locked_until = time.time() + LOCKOUT_SECONDS if count >= MAX_ATTEMPTS else 0.0
    _failed_attempts[ip] = (count, locked_until)


def _clear_failures(ip: str) -> None:
    _failed_attempts.pop(ip, None)


@app.get("/admin-dashboard/api/health")
async def health():
    return {"status": "ok", "service": "dashboard_auth"}


@app.post("/admin-dashboard/api/login")
async def login(request: Request, response: Response):
    ip = _client_ip(request)

    if _is_locked_out(ip):
        logger.warning("login locked out ip=%s", ip)
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Too many failed attempts. Try again in a minute."},
        )

    body = await request.json()
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))

    valid = hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(
        password, ADMIN_PASSWORD
    )

    if not valid:
        _record_failure(ip)
        logger.warning("login failed ip=%s username=%s", ip, username)
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid credentials"})

    _clear_failures(ip)
    token = _make_token(username)
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/admin-dashboard",
    )
    logger.info("login success ip=%s username=%s", ip, username)
    return response


@app.get("/admin-dashboard/api/session")
async def session(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    authenticated = bool(token) and _verify_token(token)
    return {"authenticated": authenticated}


@app.post("/admin-dashboard/api/logout")
async def logout():
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(key=COOKIE_NAME, path="/admin-dashboard")
    return response
