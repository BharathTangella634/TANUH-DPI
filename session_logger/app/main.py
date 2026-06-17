"""
session_logger — FastAPI microservice (port 8002)
=================================================
Persists session data into the pre-existing nhcx.session_logs table on Cloud SQL.

Table schema (existing):
    session_id    binary(16)  PK
    user_id       binary(16)  unique per ip_address (deterministic UUID from IP)
    ip_address    varchar(45)
    state         varchar(100)
    city          varchar(100)
    document_type enum('clinical_document','insurance_document')
    pdf_location  text   — filename of uploaded PDF
    json_location text   — (unused, kept for schema compatibility)
    created_at    datetime (auto IST)

Endpoints:
  POST /log              — called by pdf2abdm / pdf2nhcx after each inference
  GET  /health           — liveness probe
  GET  /logs             — paginated read of all session logs
  GET  /logs/stats       — aggregated counts (feeds dashboard cards)
"""

import uuid
import logging
from typing import Optional, Literal

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from common.secrets import load_secrets
load_secrets()

from .core.config import settings
from .db.session import Base, engine, get_db, USE_SQLITE
from .models.models import SessionLog, AuthToken, Feedback, User, OTPVerification

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Table bootstrap ───────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
logger.info("session_logger started — tables created/verified (%s).",
            "SQLite" if USE_SQLITE else "MySQL")

import hashlib
import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal, List

import bcrypt
from jose import jwt as jose_jwt, JWTError

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description=(
        "Internal logging service for the NHCX pipeline. "
        "Persists session data and auth-token grants into the nhcx database on Cloud SQL."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from common.metrics import instrument_fastapi
instrument_fastapi(app, service="session_logger")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ip_to_user_id(ip: str) -> str:
    return uuid.uuid4().hex

def _new_session_id() -> str:
    return uuid.uuid4().hex

def _doc_type_enum(service: str) -> str:
    mapping = {
        "pdf2abdm": "clinical_document",
        "pdf2nhcx": "insurance_document",
        "privacy_filter": "privacy_document",
        "forgensic": "forgery_document",
    }
    return mapping.get(service, service)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SessionLogCreate(BaseModel):
    service:      Literal["pdf2abdm", "pdf2nhcx", "privacy_filter", "forgensic"]
    ip_address:   Optional[str]  = "unknown"
    state:        Optional[str]  = None
    city:         Optional[str]  = None
    pdf_location: Optional[str]  = None
    json_location: Optional[str] = None


class AuthTokenCreate(BaseModel):
    """Payload sent by any service when it issues a demo JWT."""
    name:              str
    email:             str
    service:           str                   # pdf2abdm | pdf2nhcx | privacy-filter
    token_hash:        str                   # SHA-256 hex of the raw JWT
    access_granted_at: datetime
    access_expires_at: datetime
    expiry_days:       int       = 1
    ip_address:        Optional[str] = None
    user_agent:        Optional[str] = None
    notes:             Optional[str] = None


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Liveness probe")
def health_check():
    return {"status": "ok", "service": "session-logger"}


# ── Auth-token endpoints ──────────────────────────────────────────────────────

@app.post("/logs/auth-token", tags=["Auth Tokens"],
          summary="Record a newly issued demo bearer token",
          status_code=201)
def log_auth_token(payload: AuthTokenCreate, db: Session = Depends(get_db)):
    """
    Called by pdf2abdm, pdf2nhcx, and privacy-filter immediately after issuing
    a demo JWT.  Stores the token's SHA-256 hash (never the raw token) along
    with the requester metadata and validity window.
    """
    try:
        record = AuthToken(
            name=payload.name,
            email=payload.email,
            service=payload.service,
            token_hash=payload.token_hash,
            access_granted_at=payload.access_granted_at,
            access_expires_at=payload.access_expires_at,
            expiry_days=payload.expiry_days,
            ip_address=payload.ip_address,
            user_agent=payload.user_agent,
            notes=payload.notes,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(
            f"[auth-token] id={record.id} service={payload.service} "
            f"email={payload.email} expires={payload.access_expires_at}"
        )
        return {
            "status": "recorded",
            "id": record.id,
            "service": record.service,
            "email": record.email,
            "access_granted_at": str(record.access_granted_at),
            "access_expires_at": str(record.access_expires_at),
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[auth-token] DB write failed: {exc}")
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/logs/auth-tokens", tags=["Auth Tokens"],
         summary="Paginated list of all issued auth tokens")
def list_auth_tokens(
    skip:    int            = 0,
    limit:   int            = 50,
    service: Optional[str]  = None,
    email:   Optional[str]  = None,
    db: Session = Depends(get_db),
):
    """Returns the most-recent token grants, newest first. Filter by service or email."""
    query = db.query(AuthToken)
    if service:
        query = query.filter(AuthToken.service == service)
    if email:
        query = query.filter(AuthToken.email == email)

    total = query.count()
    rows  = query.order_by(AuthToken.id.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip":  skip,
        "limit": limit,
        "items": [
            {
                "id":                r.id,
                "name":              r.name,
                "email":             r.email,
                "service":           r.service,
                "expiry_days":       r.expiry_days,
                "access_granted_at": str(r.access_granted_at) if r.access_granted_at else None,
                "access_expires_at": str(r.access_expires_at) if r.access_expires_at else None,
                "ip_address":        r.ip_address,
                "revoked":           r.revoked,
                "revoked_at":        str(r.revoked_at) if r.revoked_at else None,
                "created_at":        str(r.created_at) if r.created_at else None,
            }
            for r in rows
        ],
    }


@app.get("/logs/auth-tokens/stats", tags=["Auth Tokens"],
         summary="Auth token issuance statistics")
def auth_token_stats(db: Session = Depends(get_db)):
    """Summary counts of tokens issued, broken down by service."""
    total = db.query(func.count(AuthToken.id)).scalar() or 0
    by_service = (
        db.query(AuthToken.service, func.count(AuthToken.id))
        .group_by(AuthToken.service)
        .all()
    )
    unique_users = (
        db.query(func.count(func.distinct(AuthToken.email))).scalar() or 0
    )
    return {
        "total_tokens_issued":  total,
        "unique_token_holders": unique_users,
        "by_service": {svc: cnt for svc, cnt in by_service},
    }


# ── Session-log write endpoint ─────────────────────────────────────────────────

@app.post("/log", tags=["Logging"], summary="Ingest a session log entry",
          status_code=201)
def create_log(payload: SessionLogCreate, db: Session = Depends(get_db)):
    """
    Called internally by pdf2abdm and pdf2nhcx via a BackgroundTask.
    Inserts one row per inference into nhcx.session_logs.

    Note: the table has UNIQUE KEY (user_id, ip_address) — duplicate IP+service
    combinations will be inserted as separate rows because session_id (PK) is
    always new.  The unique key covers user_id+ip_address, not per inference.
    We INSERT IGNORE to gracefully handle the unique constraint if the same
    user submits multiple documents.
    """
    session_id = _new_session_id()
    user_id    = _ip_to_user_id(payload.ip_address or "unknown")
    doc_type   = _doc_type_enum(payload.service)

    try:
        if USE_SQLITE:
            db.execute(
                text("""
                    INSERT OR IGNORE INTO session_logs
                        (session_id, user_id, ip_address, state, city,
                         document_type, pdf_location, json_location)
                    VALUES
                        (:session_id, :user_id, :ip_address, :state, :city,
                         :document_type, :pdf_location, :json_location)
                """),
                {
                    "session_id":    session_id,
                    "user_id":       user_id,
                    "ip_address":    payload.ip_address or "unknown",
                    "state":         payload.state,
                    "city":          payload.city,
                    "document_type": doc_type,
                    "pdf_location":  payload.pdf_location,
                    "json_location": payload.json_location,
                }
            )
        else:
            db.execute(
                text("""
                    INSERT IGNORE INTO session_logs
                        (session_id, user_id, ip_address, state, city,
                         document_type, pdf_location, json_location)
                    VALUES
                        (:session_id, :user_id, :ip_address, :state, :city,
                         :document_type, :pdf_location, :json_location)
                """),
                {
                    "session_id":    session_id,
                    "user_id":       user_id,
                    "ip_address":    payload.ip_address or "unknown",
                    "state":         payload.state,
                    "city":          payload.city,
                    "document_type": doc_type,
                    "pdf_location":  payload.pdf_location,
                    "json_location": payload.json_location,
                }
            )
        db.commit()
        logger.info(
            f"Logged [{payload.service}] ip={payload.ip_address} "
            f"doc_type={doc_type} pdf={payload.pdf_location}"
        )
        return {"status": "logged", "document_type": doc_type}

    except Exception as exc:
        db.rollback()
        logger.error(f"[session-logger] DB write failed: {exc}")
        return JSONResponse(status_code=500, content={"detail": str(exc)})


# ── Read endpoints ─────────────────────────────────────────────────────────────

@app.get("/logs", tags=["Analytics"], summary="Paginated session log listing")
def list_logs(
    skip:  int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Returns the most recent session logs (newest first)."""
    total = db.query(func.count(SessionLog.session_id)).scalar() or 0
    rows  = (
        db.query(SessionLog)
        .order_by(SessionLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "skip":  skip,
        "limit": limit,
        "items": [
            {
                "ip_address":    r.ip_address,
                "state":         r.state,
                "city":          r.city,
                "document_type": r.document_type,
                "pdf_location":  r.pdf_location,
                "json_location": r.json_location,
                "created_at":    str(r.created_at) if r.created_at else None,
            }
            for r in rows
        ],
    }


@app.get("/logs/stats", tags=["Analytics"],
         summary="Aggregated counts for dashboard cards")
def log_stats(db: Session = Depends(get_db)):
    """
    Returns aggregate statistics for the NHCX dashboard:
      total_sessions     — all rows (every unique user+IP inference)
      clinical_documents — rows where document_type = 'clinical_document'
      insurance_policies — rows where document_type = 'insurance_document'
      unique_visitors    — distinct IP addresses seen (page users)
      unique_ips         — alias for unique_visitors (legacy)
    """
    total = db.query(func.count(SessionLog.session_id)).scalar() or 0

    clinical = (
        db.query(func.count(SessionLog.session_id))
        .filter(SessionLog.document_type == "clinical_document")
        .scalar() or 0
    )
    insurance = (
        db.query(func.count(SessionLog.session_id))
        .filter(SessionLog.document_type == "insurance_document")
        .scalar() or 0
    )
    unique_ips = (
        db.query(func.count(func.distinct(SessionLog.ip_address)))
        .scalar() or 0
    )

    states = [
        r[0] for r in db.query(SessionLog.state)
        .filter(SessionLog.state.isnot(None), SessionLog.state != "")
        .distinct()
        .all()
    ]
    
    districts = [
        r[0] for r in db.query(SessionLog.city)
        .filter(SessionLog.city.isnot(None), SessionLog.city != "")
        .distinct()
        .all()
    ]

    # Token holders from auth_tokens table (Page Users — registered)
    token_holders = 0
    try:
        token_holders = (
            db.query(func.count(func.distinct(AuthToken.email))).scalar() or 0
        )
    except Exception:
        pass

    return {
        "total_sessions":      total,
        "clinical_documents":  clinical,
        "insurance_policies":  insurance,
        "unique_ips":          unique_ips,
        "unique_visitors":     unique_ips,       # page users (by IP)
        "token_holders":       token_holders,    # registered demo-token users
        "states":              states,
        "districts":           districts,
    }



@app.get("/logs/pf-stats", tags=["Analytics"],
         summary="Privacy Filter usage stats")
def pf_stats(db: Session = Depends(get_db)):
    """Return privacy filter document count from the database."""
    docs_redacted = (
        db.query(func.count(SessionLog.session_id))
        .filter(SessionLog.document_type == "privacy_document")
        .scalar() or 0
    )
    return {
        "page_visits":    0,
        "docs_redacted":  docs_redacted,
        "unique_visitors": 0,
    }


@app.get("/logs/forgensic-stats", tags=["Analytics"],
         summary="Forgensic usage stats")
def forgensic_stats(db: Session = Depends(get_db)):
    """Return forgery detection document count from the database."""
    docs_analyzed = (
        db.query(func.count(SessionLog.session_id))
        .filter(SessionLog.document_type == "forgery_document")
        .scalar() or 0
    )
    return {
        "docs_analyzed": docs_analyzed,
        "active_jobs":   0,
    }


# ── NHCX Page Visit tracking ──────────────────────────────────────────────────

class PageVisitCreate(BaseModel):
    page:  str           = "nhcx-hackathon"
    state: Optional[str] = None
    city:  Optional[str] = None


@app.post("/logs/visit", tags=["Analytics"],
          summary="Record a NHCX website page visit",
          status_code=201)
def record_visit(payload: PageVisitCreate, db: Session = Depends(get_db)):
    """
    Called by the frontend dashboard.js once per browser session.
    Inserts a row into the page_visits table so NHCX web traffic
    can be tracked over time.
    Table is created on first call (checkfirst=True).
    """
    from sqlalchemy import Column, Integer, String, DateTime, inspect
    from datetime import datetime

    # Ensure the page_visits table exists
    try:
        if USE_SQLITE:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS page_visits (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    page       VARCHAR(100) NOT NULL DEFAULT 'nhcx-hackathon',
                    state      VARCHAR(100),
                    city       VARCHAR(100),
                    visited_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS page_visits (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    page       VARCHAR(100) NOT NULL DEFAULT 'nhcx-hackathon',
                    state      VARCHAR(100),
                    city       VARCHAR(100),
                    visited_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        db.commit()
    except Exception as exc:
        logger.warning("[visit] Table check failed: %s", exc)

    try:
        db.execute(
            text("INSERT INTO page_visits (page, state, city) VALUES (:page, :state, :city)"),
            {"page": payload.page, "state": payload.state, "city": payload.city},
        )
        db.commit()
        logger.info("[visit] Recorded visit page=%s state=%s city=%s", payload.page, payload.state, payload.city)
        return {"status": "recorded", "page": payload.page}
    except Exception as exc:
        db.rollback()
        logger.error("[visit] DB write failed: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/logs/visit/stats", tags=["Analytics"],
         summary="NHCX page visit counts over time")
def visit_stats(db: Session = Depends(get_db)):
    """Returns total NHCX website page views and unique locations."""
    try:
        total = db.execute(text("SELECT COUNT(*) FROM page_visits")).scalar() or 0
        states = [
            r[0] for r in db.execute(
                text("SELECT DISTINCT state FROM page_visits WHERE state IS NOT NULL AND state != ''")
            ).fetchall()
        ]
        cities = [
            r[0] for r in db.execute(
                text("SELECT DISTINCT city FROM page_visits WHERE city IS NOT NULL AND city != ''")
            ).fetchall()
        ]
        return {"nhcx_page_visits": total, "states": states, "cities": cities}
    except Exception as exc:
        logger.warning("[visit-stats] query failed: %s", exc)
        return {"nhcx_page_visits": 0, "states": [], "cities": []}


# ── Feedback ─────────────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    service:    str
    name:       Optional[str] = "Anonymous"
    place:      Optional[str] = "Anonymous place"
    feedback:   str
    ip_address: Optional[str] = None


@app.post("/logs/feedback", tags=["Feedback"],
          summary="Submit user feedback for a service",
          status_code=201)
def submit_feedback(payload: FeedbackCreate, request: Request, db: Session = Depends(get_db)):
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
        or payload.ip_address
    )
    try:
        record = Feedback(
            service=payload.service,
            name=payload.name or "Anonymous",
            place=payload.place or "Anonymous place",
            feedback=payload.feedback,
            ip_address=client_ip,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info("[feedback] id=%d service=%s name=%s", record.id, record.service, record.name)
        return {"status": "recorded", "id": record.id}
    except Exception as exc:
        db.rollback()
        logger.error("[feedback] DB write failed: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/logs/feedback", tags=["Feedback"],
         summary="List all feedback entries")
def list_feedback(
    skip: int = 0, limit: int = 50,
    service: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Feedback)
    if service:
        query = query.filter(Feedback.service == service)
    total = query.count()
    rows = query.order_by(Feedback.id.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {"id": r.id, "service": r.service, "name": r.name, "place": r.place,
             "feedback": r.feedback, "ip_address": r.ip_address,
             "created_at": str(r.created_at) if r.created_at else None}
            for r in rows
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# User Authentication — Register / Login / OTP / Google OAuth
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_SECRET = os.getenv("DPI_AUTH_SECRET_KEY", "dpi-dev-secret-change-me")
_AUTH_ALGORITHM = "HS256"
_AUTH_TOKEN_DAYS = int(os.getenv("DPI_AUTH_TOKEN_DAYS", "7"))

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@tanuh.ai")


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _issue_auth_jwt(user_id: int, email: str, name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": name,
        "type": "dpi_user",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=_AUTH_TOKEN_DAYS)).timestamp()),
    }
    return jose_jwt.encode(payload, _AUTH_SECRET, algorithm=_AUTH_ALGORITHM)


def _decode_auth_jwt(token: str) -> dict:
    return jose_jwt.decode(token, _AUTH_SECRET, algorithms=[_AUTH_ALGORITHM])


def _generate_otp() -> str:
    return f"{random.SystemRandom().randint(0, 999999):06d}"


def _send_otp_email(email: str, otp: str, name: str) -> bool:
    if not SMTP_HOST:
        logger.info("[auth] SMTP not configured — OTP for %s: %s (dev mode)", email, otp)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "TANUH DPI — Your Verification Code"
    msg["From"] = SMTP_FROM
    msg["To"] = email

    html = f"""\
    <div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
        <div style="text-align:center;margin-bottom:24px;">
            <h2 style="color:#14868C;margin:0;">TANUH DPI</h2>
            <p style="color:#6b7280;font-size:14px;">AI Centre of Excellence in Healthcare</p>
        </div>
        <p>Hi {name},</p>
        <p>Your verification code is:</p>
        <div style="text-align:center;margin:24px 0;">
            <span style="display:inline-block;font-size:32px;font-weight:700;letter-spacing:8px;
                         color:#14868C;background:#f0fdfa;padding:16px 32px;border-radius:12px;
                         border:2px solid #d8eeee;">{otp}</span>
        </div>
        <p style="color:#6b7280;font-size:14px;">This code expires in 10 minutes. If you didn't request this, please ignore this email.</p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
        <p style="color:#9ca3af;font-size:12px;text-align:center;">TANUH &middot; AI Centre of Excellence &middot; IISc Bangalore</p>
    </div>"""

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, email, msg.as_string())
        logger.info("[auth] OTP email sent to %s", email)
        return True
    except Exception as exc:
        logger.error("[auth] Failed to send OTP email to %s: %s", email, exc)
        return False


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class OTPVerifyRequest(BaseModel):
    email: str
    otp: str

class GoogleAuthRequest(BaseModel):
    credential: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/auth/register", tags=["User Auth"],
          summary="Register a new user with email",
          status_code=201)
def auth_register(body: RegisterRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    body.name = body.name.strip()

    if not body.name or not body.email or not body.password:
        raise HTTPException(400, "Name, email, and password are required.")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")

    existing = db.query(User).filter(User.email == body.email).first()
    if existing and existing.is_verified:
        raise HTTPException(409, "An account with this email already exists.")

    if existing and not existing.is_verified:
        existing.name = body.name
        existing.password_hash = _hash_password(body.password)
        db.commit()
    else:
        user = User(
            name=body.name,
            email=body.email,
            password_hash=_hash_password(body.password),
            provider="email",
            is_verified=False,
        )
        db.add(user)
        db.commit()

    otp = _generate_otp()
    otp_record = OTPVerification(
        email=body.email,
        otp_hash=hashlib.sha256(otp.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(otp_record)
    db.commit()

    email_sent = _send_otp_email(body.email, otp, body.name)

    response_data = {
        "status": "otp_sent",
        "email": body.email,
        "message": "A verification code has been sent to your email.",
    }
    if not email_sent:
        response_data["dev_otp"] = otp

    return response_data


@app.post("/auth/verify-otp", tags=["User Auth"],
          summary="Verify email with OTP code")
def auth_verify_otp(body: OTPVerifyRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()
    otp_hash = hashlib.sha256(body.otp.strip().encode()).hexdigest()

    record = (
        db.query(OTPVerification)
        .filter(
            OTPVerification.email == body.email,
            OTPVerification.otp_hash == otp_hash,
        )
        .order_by(OTPVerification.id.desc())
        .first()
    )

    if not record:
        raise HTTPException(400, "Invalid verification code.")

    if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(400, "Verification code has expired. Please request a new one.")

    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(404, "User not found.")

    user.is_verified = True
    db.query(OTPVerification).filter(OTPVerification.email == body.email).delete()
    db.commit()

    token = _issue_auth_jwt(user.id, user.email, user.name)
    return {
        "status": "verified",
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "provider": user.provider},
    }


@app.post("/auth/login", tags=["User Auth"],
          summary="Login with email and password")
def auth_login(body: LoginRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash:
        raise HTTPException(401, "Invalid email or password.")
    if not user.is_verified:
        raise HTTPException(403, "Email not verified. Please complete registration first.")
    if not _check_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")

    token = _issue_auth_jwt(user.id, user.email, user.name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "provider": user.provider},
    }


@app.post("/auth/google", tags=["User Auth"],
          summary="Authenticate with Google OAuth credential")
def auth_google(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        google_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        if not google_client_id:
            raise HTTPException(501, "Google OAuth is not configured on this server.")

        idinfo = id_token.verify_oauth2_token(
            body.credential, google_requests.Request(), google_client_id
        )
        email = idinfo["email"].lower()
        name = idinfo.get("name", email.split("@")[0])
        google_sub = idinfo["sub"]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[auth] Google token verification failed: %s", exc)
        raise HTTPException(401, "Invalid Google credential.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            name=name,
            email=email,
            provider="google",
            google_id=google_sub,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.google_id:
        user.google_id = google_sub
        if not user.is_verified:
            user.is_verified = True
        db.commit()

    token = _issue_auth_jwt(user.id, user.email, user.name)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "provider": user.provider},
    }


@app.get("/auth/me", tags=["User Auth"],
         summary="Get current user profile from JWT")
def auth_me(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header.")

    token = auth_header[7:]
    try:
        claims = _decode_auth_jwt(token)
    except JWTError as exc:
        raise HTTPException(401, f"Invalid or expired token: {exc}")

    user = db.query(User).filter(User.id == int(claims["sub"])).first()
    if not user:
        raise HTTPException(404, "User not found.")

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "provider": user.provider,
        "is_verified": user.is_verified,
        "created_at": str(user.created_at) if user.created_at else None,
    }


@app.post("/auth/resend-otp", tags=["User Auth"],
          summary="Resend OTP to email")
def auth_resend_otp(body: OTPVerifyRequest, db: Session = Depends(get_db)):
    body.email = body.email.strip().lower()

    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(404, "No account found with this email.")
    if user.is_verified:
        raise HTTPException(400, "Email is already verified.")

    db.query(OTPVerification).filter(OTPVerification.email == body.email).delete()
    db.commit()

    otp = _generate_otp()
    otp_record = OTPVerification(
        email=body.email,
        otp_hash=hashlib.sha256(otp.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(otp_record)
    db.commit()

    email_sent = _send_otp_email(body.email, otp, user.name)

    response_data = {"status": "otp_sent", "email": body.email}
    if not email_sent:
        response_data["dev_otp"] = otp
    return response_data

