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

import os
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
from .models.models import SessionLog, AuthToken, Feedback, User

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Table bootstrap ───────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
logger.info("session_logger started — tables created/verified (%s).",
            "SQLite" if USE_SQLITE else "MySQL")

# Programmatic schema migrations for existing tables
try:
    from sqlalchemy import inspect
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns("auth_tokens")]
    
    with engine.begin() as conn:
        if "encrypted_token" not in columns:
            logger.info("Migrating auth_tokens table: adding encrypted_token column")
            conn.execute(text("ALTER TABLE auth_tokens ADD COLUMN encrypted_token TEXT"))
            
        if "created_date" not in columns:
            logger.info("Migrating auth_tokens table: adding created_date column")
            conn.execute(text("ALTER TABLE auth_tokens ADD COLUMN created_date VARCHAR(10)"))
            
            # Also attempt to add a unique composite constraint/index
            try:
                if USE_SQLITE:
                    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT directly.
                    # We can index it or let the nested transaction handle it on SQLite.
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_email_service_date ON auth_tokens (email, service, created_date)"))
                else:
                    logger.info("Migrating auth_tokens table: adding uq_email_service_date unique constraint")
                    conn.execute(text("ALTER TABLE auth_tokens ADD CONSTRAINT uq_email_service_date UNIQUE (email, service, created_date)"))
            except Exception as index_err:
                logger.warning(f"Composite unique constraint creation bypassed/failed: {index_err}")
except Exception as migration_err:
    logger.warning(f"Table bootstrap migration warning: {migration_err}")

# ── Production Auth Safety Check (Session 4) ───────────────────────────────
def _check_production_auth_safety():
    is_prod = os.getenv("ENV", "").lower() in ("prod", "production") or os.getenv("MYSQL_HOST") == "cloud-sql-proxy"
    
    bypass_flags = {
        "ABDM_AUTH_ENABLED": os.getenv("ABDM_AUTH_ENABLED", "true"),
        "NHCX_AUTH_ENABLED": os.getenv("NHCX_AUTH_ENABLED", "true"),
        "KEYCLOAK_AUTH_ENABLED": os.getenv("KEYCLOAK_AUTH_ENABLED", "true"),
        "FORGENSIC_AUTH_ENABLED": os.getenv("FORGENSIC_AUTH_ENABLED", "true"),
    }
    
    for flag, val in bypass_flags.items():
        if val.lower() in ("false", "0", "no"):
            msg = f"CRITICAL SECURITY WARNING: Auth bypass is ACTIVE ({flag}={val})!"
            if is_prod:
                logger.critical(f"{msg} In production mode, auth bypass is STRICTLY FORBIDDEN. Startup aborted!")
                raise RuntimeError(f"Production auth safety violation: {flag} is disabled.")
            else:
                logger.warning(f"{msg} Permitted ONLY because ENV is set to local/development mode.")

_check_production_auth_safety()

import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal, List
import jwt
import time
import base64
import hashlib
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

import json as _json
import firebase_admin
from firebase_admin import credentials as fb_credentials, auth as fb_auth

_fb_key_raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY", "")
if _fb_key_raw and _fb_key_raw.strip().startswith("{"):
    _fb_cred = fb_credentials.Certificate(_json.loads(_fb_key_raw))
    firebase_admin.initialize_app(_fb_cred)
    logger.info("[firebase] Initialized with service account JSON from env/Secret Manager")
elif _fb_key_raw and os.path.isfile(_fb_key_raw):
    _fb_cred = fb_credentials.Certificate(_fb_key_raw)
    firebase_admin.initialize_app(_fb_cred)
    logger.info("[firebase] Initialized with service account file: %s", _fb_key_raw)
else:
    firebase_admin.initialize_app()
    logger.info("[firebase] Initialized with Application Default Credentials")

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description=(
        "Internal logging service for the NHCX pipeline. "
        "Persists session data and auth-token grants into the nhcx database on Cloud SQL."
    ),
)

from common.rate_limit import RequestIDMiddleware, register_standard_error_handlers

app.add_middleware(RequestIDMiddleware)
register_standard_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from common.metrics import instrument_fastapi
instrument_fastapi(app, service="session_logger")


# ── Daily Expired Token Cleanup Loop (Session 4.1) ───────────────────────────
import asyncio

async def _token_cleanup_worker():
    """Cooperative, non-blocking background task running within FastAPI's native event loop."""
    logger.info("[cleanup] Cooperative token lifecycle scheduler started successfully")
    try:
        db = SessionLocal()
        cutoff = datetime.now() - timedelta(days=30)
        logger.info(f"[cleanup] Startup run: Purging developer tokens older than 30 days (created before {cutoff})")
        deleted = db.query(AuthToken).filter(AuthToken.created_at < cutoff).delete()
        db.commit()
        db.close()
        logger.info(f"[cleanup] Startup run: Purged {deleted} expired developer tokens successfully")
    except Exception as exc:
        logger.error(f"[cleanup] Startup expired token cleanup failed: {exc}")

    while True:
        await asyncio.sleep(86400)
        try:
            db = SessionLocal()
            cutoff = datetime.now() - timedelta(days=30)
            logger.info(f"[cleanup] Cooperative run: Purging developer tokens older than 30 days (created before {cutoff})")
            deleted = db.query(AuthToken).filter(AuthToken.created_at < cutoff).delete()
            db.commit()
            db.close()
            logger.info(f"[cleanup] Cooperative run: Purged {deleted} expired developer tokens successfully")
        except Exception as exc:
            logger.error(f"[cleanup] Cooperative expired token cleanup failed: {exc}")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_token_cleanup_worker())


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
# User Authentication — Firebase ID Token Verification
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import HTTPException


def _verify_firebase_token(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header.")
    id_token = auth_header[7:]
    try:
        return fb_auth.verify_id_token(id_token)
    except Exception as exc:
        logger.warning("[auth] Firebase token verification failed: %s", exc)
        raise HTTPException(401, "Invalid or expired Firebase token.")


def _upsert_user(claims: dict, db: Session) -> User:
    uid = claims["uid"]
    user = db.query(User).filter(User.firebase_uid == uid).first()
    if user:
        changed = False
        if claims.get("email") and user.email != claims["email"]:
            user.email = claims["email"]
            changed = True
        if claims.get("name") and user.full_name != claims.get("name"):
            user.full_name = claims.get("name")
            changed = True
        if changed:
            db.commit()
        return user
    user = User(
        firebase_uid=uid,
        email=claims.get("email", ""),
        full_name=claims.get("name", ""),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("[auth] Provisioned new user uid=%s email=%s", uid, user.email)
    return user


@app.get("/auth/me", tags=["User Auth"],
         summary="Get current user profile (Firebase)")
def auth_me(request: Request, db: Session = Depends(get_db)):
    claims = _verify_firebase_token(request)
    user = _upsert_user(claims, db)
    return {
        "id": user.id,
        "firebase_uid": user.firebase_uid,
        "name": user.full_name,
        "email": user.email,
        "role": user.role,
        "created_at": str(user.created_at) if user.created_at else None,
    }


@app.post("/auth/sync", tags=["User Auth"],
          summary="Sync Firebase user to Cloud SQL",
          status_code=200)
def auth_sync(request: Request, db: Session = Depends(get_db)):
    claims = _verify_firebase_token(request)
    user = _upsert_user(claims, db)
    return {
        "status": "synced",
        "id": user.id,
        "firebase_uid": user.firebase_uid,
        "email": user.email,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Centralized API Developer Token Issuance (Session 1)
# ══════════════════════════════════════════════════════════════════════════════

class ServiceTokenRequest(BaseModel):
    service: str  # must be one of pdf2abdm, pdf2nhcx, privacy_filter, forgensic


def _get_fernet_cipher() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        salt = os.getenv("MYSQL_PASSWORD", "tanuh-dpi-fallback-secret-salt-12345!")
        key_bytes = hashlib.sha256(salt.encode()).digest()
        key = base64.urlsafe_b64encode(key_bytes).decode()
    try:
        return Fernet(key.encode())
    except Exception:
        fallback_key = base64.urlsafe_b64encode(b"tanuh_fallback_fernet_key_32_bytes_!")
        return Fernet(fallback_key)


def _encrypt_token(raw_jwt: str) -> str:
    cipher = _get_fernet_cipher()
    return cipher.encrypt(raw_jwt.encode()).decode()


def _decrypt_token(encrypted_jwt: str) -> str:
    cipher = _get_fernet_cipher()
    return cipher.decrypt(encrypted_jwt.encode()).decode()


def _issue_jwt_for_service(service: str, name: str, email: str, expiry_days: int = 1) -> str:
    if service == "pdf2abdm":
        secret = os.getenv("ABDM_SECRET_KEY", "dev")
    elif service == "pdf2nhcx":
        secret = os.getenv("NHCX_SECRET_KEY", "dev")
    elif service in ("privacy_filter", "privacy-filter"):
        secret = os.getenv("SECRET_KEY", "dev")
    elif service == "forgensic":
        secret = os.getenv("FORGENSIC_SECRET_KEY", "dev")
    else:
        raise ValueError(f"Unknown service: {service}")

    now = int(time.time())
    payload = {
        "sub": email,
        "name": name,
        "email": email,
        "type": "demo",
        "service": service,
        "iat": now,
        "exp": now + expiry_days * 86400,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@app.post("/auth/token", tags=["User Auth"], summary="Request or retrieve a service developer token", status_code=201)
def generate_service_token(payload: ServiceTokenRequest, request: Request, db: Session = Depends(get_db)):
    """
    Centralized secure endpoint to issue or retrieve developer tokens.
    1. Validates the Firebase ID token in the Authorization header.
    2. Checks whether the user's role is 'authorized' or 'admin'.
    3. Guarantees that at most one token is issued per user per service per day.
    4. Automatically returns the existing token if already generated today (200 OK).
    5. Leverages transaction nested savepoints and unique DB constraints to handle concurrency safely.
    """
    # 1. Require authenticated Firebase user
    claims = _verify_firebase_token(request)
    user = _upsert_user(claims, db)

    # 2. Check if user is authorized
    if user.role not in ("authorized", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Account is not authorized to generate API developer tokens."
        )

    # 3. Validate service
    allowed_services = {"pdf2abdm", "pdf2nhcx", "privacy_filter", "privacy-filter", "forgensic"}
    if payload.service not in allowed_services:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service. Must be one of: {', '.join(allowed_services)}"
        )

    # Normalize service name (privacy_filter is table standard)
    normalized_service = payload.service
    if normalized_service == "privacy-filter":
        normalized_service = "privacy_filter"

    # Define today's date string for constraint
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Start a transaction-level locking savepoint
    db.begin_nested()
    try:
        existing = (
            db.query(AuthToken)
            .filter(
                AuthToken.email == user.email,
                AuthToken.service == normalized_service,
                AuthToken.created_date == today_str,
                AuthToken.revoked == False
            )
            .with_for_update()
            .first()
        )

        request_id = getattr(request.state, "request_id", "unknown")

        if existing:
            try:
                decrypted = _decrypt_token(existing.encrypted_token)
                from common.rate_limit import DPI_EXISTING_TOKEN_RETURNED_TOTAL
                DPI_EXISTING_TOKEN_RETURNED_TOTAL.labels(service=payload.service).inc()
                
                logger.info(f"[auth] Existing token returned for {user.email} service={payload.service} request_id={request_id}")
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "existing_token_returned",
                        "access_token": decrypted,
                        "token_type": "bearer",
                        "service": payload.service,
                        "name": existing.name,
                        "email": existing.email,
                        "expires_at": str(existing.access_expires_at),
                    }
                )
            except Exception as dec_err:
                logger.error(f"[auth] Failed to decrypt existing token [request_id={request_id}]: {dec_err}")

        # 4. Determine token expiry in days
        expiry_env_map = {
            "pdf2abdm": "ABDM_TOKEN_EXPIRY_DAYS",
            "pdf2nhcx": "NHCX_TOKEN_EXPIRY_DAYS",
            "privacy_filter": "DEMO_TOKEN_EXPIRY_DAYS",
            "forgensic": "FORGENSIC_TOKEN_EXPIRY_DAYS"
        }
        expiry_days = int(os.getenv(expiry_env_map.get(normalized_service, "DEMO_TOKEN_EXPIRY_DAYS"), "1"))
        
        # 5. Generate and encrypt the new token
        raw_token = _issue_jwt_for_service(normalized_service, user.full_name or "User", user.email, expiry_days)
        encrypted_token = _encrypt_token(raw_token)
        token_hash = AuthToken.hash_token(raw_token)

        access_granted_at = datetime.now()
        access_expires_at = access_granted_at + timedelta(days=expiry_days)

        ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
        user_agent = request.headers.get("User-Agent")

        record = AuthToken(
            name=user.full_name or "User",
            email=user.email,
            service=normalized_service,
            token_hash=token_hash,
            access_granted_at=access_granted_at,
            access_expires_at=access_expires_at,
            expiry_days=expiry_days,
            ip_address=ip_address,
            user_agent=user_agent,
            encrypted_token=encrypted_token,
            created_date=today_str,
        )

        db.add(record)
        db.commit()

        from common.rate_limit import DPI_TOKENS_GENERATED_TOTAL
        DPI_TOKENS_GENERATED_TOTAL.labels(service=payload.service).inc()

        logger.info(f"[auth] Generated new developer token for {user.email} service={payload.service} request_id={request_id}")
        return JSONResponse(
            status_code=201,
            content={
                "status": "new_token_generated",
                "access_token": raw_token,
                "token_type": "bearer",
                "service": payload.service,
                "name": record.name,
                "email": record.email,
                "expires_at": str(record.access_expires_at),
            }
        )

    except IntegrityError:
        db.rollback()
        # Fallback in case of concurrent insert race-condition
        existing = (
            db.query(AuthToken)
            .filter(
                AuthToken.email == user.email,
                AuthToken.service == normalized_service,
                AuthToken.created_date == today_str,
                AuthToken.revoked == False
            )
            .first()
        )
        if existing:
            try:
                decrypted = _decrypt_token(existing.encrypted_token)
                from common.rate_limit import DPI_EXISTING_TOKEN_RETURNED_TOTAL
                DPI_EXISTING_TOKEN_RETURNED_TOTAL.labels(service=payload.service).inc()
                
                logger.info(f"[auth] Concurrent fallback: returning existing token for {user.email} service={payload.service} request_id={request_id}")
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "existing_token_returned",
                        "access_token": decrypted,
                        "token_type": "bearer",
                        "service": payload.service,
                        "name": existing.name,
                        "email": existing.email,
                        "expires_at": str(existing.access_expires_at),
                    }
                )
            except Exception as dec_err:
                raise HTTPException(500, f"Token was already generated today, but decryption failed [request_id={request_id}]: {dec_err}")
        raise HTTPException(409, f"A developer token was already generated today for this service [request_id={request_id}].")
    except Exception as exc:
        db.rollback()
        logger.error(f"[auth] Centralized token generation error [request_id={request_id}]: {exc}")
        raise HTTPException(500, f"Token generation failed [request_id={request_id}]: {exc}")

