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

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from .core.config import settings
from .db.session import Base, engine, get_db, USE_SQLITE
from .models.models import SessionLog, AuthToken

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Table bootstrap ───────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)
logger.info("session_logger started — tables created/verified (%s).",
            "SQLite" if USE_SQLITE else "MySQL")

import hashlib
from datetime import datetime, timedelta
from typing import Optional, Literal, List

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ip_to_user_id(ip: str) -> bytes:
    return uuid.uuid4().bytes

def _new_session_id() -> bytes:
    return uuid.uuid4().bytes

def _doc_type_enum(service: str) -> str:
    return "clinical_document" if service == "pdf2abdm" else "insurance_document"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SessionLogCreate(BaseModel):
    service:      Literal["pdf2abdm", "pdf2nhcx"]
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
def pf_stats():
    """Return zeroed stats (cloud persistence removed)."""
    return {
        "page_visits":    0,
        "docs_redacted":  0,
        "unique_visitors": 0,
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

