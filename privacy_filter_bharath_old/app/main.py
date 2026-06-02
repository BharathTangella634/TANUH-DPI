"""FastAPI app: Privacy Filter de-identification service (MedDeID backend).

Drop-in replacement for the original privacy_filter service. Same API contract
— so the TANUH-DPI frontend, session logger, auth, and storage all keep
working — but the redaction engine is now MedDeID, which removes PHI from
medical images, DICOM/NIfTI scans, and documents (both metadata tags AND
burned-in pixel text) without altering any clinical content.

Endpoints
---------
GET  /                          → redirect to API docs (frontend is a separate service)
GET  /api/health                → liveness + engine status
GET  /api/supported-types       → list of accepted file extensions
GET  /api/stats                 → live usage counters
POST /api/demo-token            → self-service JWT (name + email → signed token)
POST /api/redact                → multipart upload; returns RedactionResult  [auth required]
GET  /api/files/{kind}/{key}    → download originals or redacted outputs      [auth required]
"""
from __future__ import annotations

import gc
import logging
import os
import tempfile
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from jose import jwt
from pydantic import BaseModel, EmailStr

from .auth import require_bearer
from .schemas import Entity, HealthResponse, RedactionResult
from .stats import get_stats, record_redaction, record_visit
from .storage import get_storage, _guess_content_type
from . import service

load_dotenv()

SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("privacy_filter")


def _fire_log(payload: dict) -> None:
    """POST a session log entry to the logger service. Never raises."""
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{SESSION_LOGGER_URL}/log", json=payload)
    except Exception as exc:
        logger.warning("[session-logger] fire-and-forget failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the engine so the first request is fast.
    try:
        service.engine_ready()
    except Exception:
        logger.exception("MedDeID engine failed to initialise at startup")
    yield


app = FastAPI(
    title="Privacy Filter — MedDeID",
    version="1.0.0",
    description=(
        "Upload a medical image, DICOM/NIfTI scan, or document → detect & "
        "remove patient information (metadata tags + burned-in pixel text) "
        "using the MedDeID de-identification engine."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() \
                or (request.client.host if request.client else None)
    try:
        record_visit(client_ip)
    except Exception:
        pass  # Never let stats tracking break the page load.
    return RedirectResponse("/docs")


@app.get("/api/health", response_model=HealthResponse)
async def health():
    ready = service.engine_ready()
    return HealthResponse(
        status="ok" if ready else "loading",
        model="Privacy Filter",
        device="cpu",
        model_loaded=ready,
    )


@app.get("/api/supported-types")
async def supported_types():
    return {"extensions": service.supported_extensions()}


# ---------------------------------------------------------------------------
# Demo token — self-service JWT issuance
# ---------------------------------------------------------------------------

class DemoTokenRequest(BaseModel):
    name: str
    email: EmailStr


@app.post("/api/demo-token")
async def create_demo_token(body: DemoTokenRequest):
    """Issue a signed demo JWT for the given name + email."""
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Demo tokens are not available: SECRET_KEY is not configured.",
        )

    expiry_days = int(os.getenv("DEMO_TOKEN_EXPIRY_DAYS", "1"))
    now = int(time.time())
    payload = {
        "sub": body.email,
        "name": body.name,
        "email": body.email,
        "type": "demo",
        "iat": now,
        "exp": now + expiry_days * 86_400,
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    logger.info("Demo token issued for %s (%s), expires in %dd",
                body.name, body.email, expiry_days)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_days": expiry_days,
        "name": body.name,
        "email": body.email,
    }


@app.post("/api/redact", response_model=RedactionResult)
async def redact_file(
    request: Request,
    file: UploadFile = File(...),
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    if not service.is_supported(file.filename):
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type. Supported: "
                f"{', '.join(service.supported_extensions())}"
            ),
        )

    storage = get_storage()
    job_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename).name
    upload_key = f"{job_id}__{safe_name}"

    raw_bytes: bytes | None = None
    try:
        raw_bytes = await file.read()

        # Write upload to a local temp path the engine can read directly.
        tmp_upload_dir = Path(tempfile.gettempdir()) / "pf_uploads"
        tmp_upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = tmp_upload_dir / upload_key
        upload_path.write_bytes(raw_bytes)

        # Persist the original to configured storage (GCS or local).
        storage.save("uploads", upload_key, raw_bytes)
        raw_bytes = None  # drop the in-memory copy

        # Produce the de-identified output (format-preserving).
        out_ext = service.out_extension(safe_name)
        redacted_key = f"{job_id}__redacted{out_ext}"
        tmp_redact_dir = Path(tempfile.gettempdir()) / "pf_redacted"
        tmp_redact_dir.mkdir(parents=True, exist_ok=True)
        redacted_local = tmp_redact_dir / redacted_key

        try:
            entities_raw, counts, meta = service.run_deidentification(
                upload_path, redacted_local,
            )
        except Exception as e:
            logger.exception("De-identification failed")
            raise HTTPException(status_code=500, detail=f"De-identification failed: {e}")

        if not redacted_local.exists():
            raise HTTPException(
                status_code=500,
                detail="Engine completed but produced no output file.",
            )

        # Upload redacted output to storage.
        with open(redacted_local, "rb") as fh:
            storage.save("redacted", redacted_key, fh.read())

        entities = [Entity(**e) for e in entities_raw]

        notes = None
        if not meta.get("validation_passed", False):
            notes = (
                f"Validation risk score {meta.get('risk_score', 0)}. "
                f"{meta.get('notes') or ''}".strip()
            )

        result = RedactionResult(
            job_id=job_id,
            filename=safe_name,
            content_type=file.content_type or "application/octet-stream",
            entities=entities,
            entity_counts=dict(Counter(counts)),
            original_url=storage.url("uploads", upload_key),
            redacted_url=storage.url("redacted", redacted_key),
            text_preview_original=None,   # binary medical formats: no text preview
            text_preview_redacted=None,
            notes=notes,
        )

        try:
            record_redaction()
        except Exception:
            pass

        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() \
                    or (request.client.host if request.client else "unknown")
        _fire_log({
            "service": "privacy_filter",
            "ip_address": client_ip,
            "pdf_location": safe_name,
        })
        return result
    finally:
        raw_bytes = None
        gc.collect()


@app.get("/api/files/{kind}/{key}")
async def download_file(
    kind: str,
    key: str,
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    if kind not in {"uploads", "redacted"}:
        raise HTTPException(status_code=404, detail="Unknown kind")
    storage = get_storage()
    if os.getenv("STORAGE_BACKEND", "local").lower() == "gcs":
        try:
            data = storage.open_read(kind, key)
        except Exception as e:
            logger.exception("GCS download failed")
            raise HTTPException(status_code=404, detail=f"File not found in GCS: {e}")
        filename = key.split("__", 1)[-1]
        content_type = _guess_content_type(filename)
        return StreamingResponse(
            data,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    p = storage.local_path(kind, key)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(p, filename=key.split("__", 1)[-1])


@app.get("/api/stats")
async def stats():
    """Return usage counters from the session logger database."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{SESSION_LOGGER_URL}/logs/pf-stats")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning("Session logger stats fetch failed: %s", e)
    try:
        return get_stats()
    except Exception:
        return {"page_visits": 0, "unique_visitors": 0, "docs_redacted": 0}
