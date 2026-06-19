"""
NHA PS3 Forensics API — Production-ready with Celery + Redis.

Architecture
------------
  POST /jobs          →  save upload to shared volume  →  enqueue Celery task
  GET  /jobs/{id}     →  read job state from Redis
  GET  /jobs/{id}/results  →  read full result from Redis
  GET  /jobs/{id}/files/{name}  →  serve file from shared disk

State is stored in Redis (key: forgensic:job:{job_id}) so any API replica
can answer status queries regardless of which worker processed the job.
Files are served from the shared volume (DATA_DIR) — no binary blobs in Redis.
"""
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import redis as redis_lib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, EmailStr

from common.secrets import load_secrets
load_secrets()

from .config import (
    CORS_ORIGINS,
    DATA_DIR,
    JOB_TTL_SECONDS,
    MAX_UPLOAD_BYTES,
    OCR_ENABLED,
    PIPELINE_PRESET,
    PIPELINE_VERSION,
    REDIS_URL,
)
from .auth import require_bearer, issue_demo_token
from .models import JobCreateResponse, JobResultResponse, JobStatusResponse

app = FastAPI(title="NHA PS3 Forensics API")

from common.rate_limit import RateLimitMiddleware, RequestIDMiddleware, register_standard_error_handlers

app.add_middleware(RequestIDMiddleware)
register_standard_error_handlers(app)

app.add_middleware(
    RateLimitMiddleware,
    service_name="forgensic",
    limit=150
)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

from common.metrics import instrument_fastapi
instrument_fastapi(app, service="forgensic")

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Redis client (lazy, per-request) ──────────────────────────────────────────

def _get_redis() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


def _job_key(job_id: str) -> str:
    return f"forgensic:job:{job_id}"


# ── Misc helpers ──────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    name: str
    email: EmailStr


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _allowed_suffix(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _save_upload(upload: UploadFile, dest: Path) -> int:
    """Stream the upload to *dest*, enforcing the size limit."""
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as f:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return size


def _write_job_state(job_id: str, payload: Dict[str, Any]) -> None:
    """Merge *payload* into the Redis record for *job_id*."""
    r = _get_redis()
    key = _job_key(job_id)
    raw = r.get(key)
    state: Dict[str, Any] = json.loads(raw) if raw else {}
    state.update(payload)
    r.set(key, json.dumps(state, default=str), ex=JOB_TTL_SECONDS)


def _read_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    r = _get_redis()
    raw = r.get(_job_key(job_id))
    return json.loads(raw) if raw else None


def _cleanup_jobs() -> None:
    """
    Remove disk artefacts for jobs whose Redis key has already expired.
    Iterates DATA_DIR subdirs and removes any whose job is no longer in Redis.
    Fast check: if Redis key absent → TTL elapsed → safe to delete.
    """
    if JOB_TTL_SECONDS <= 0:
        return
    try:
        r = _get_redis()
        for job_dir in list(DATA_DIR.iterdir()):
            if not job_dir.is_dir():
                continue
            job_id = job_dir.name
            if not r.exists(_job_key(job_id)):
                shutil.rmtree(job_dir, ignore_errors=True)
    except Exception:
        pass  # never let cleanup crash an endpoint


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    _cleanup_jobs()
    try:
        r = _get_redis()
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"ok": redis_ok, "time": _now_iso(), "redis": redis_ok}


@app.get("/stats")
async def stats() -> Dict[str, Any]:
    docs_analyzed = 0
    active = 0
    try:
        import httpx
        session_logger_url = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")
        resp = httpx.get(f"{session_logger_url}/logs/forgensic-stats", timeout=5.0)
        if resp.status_code == 200:
            docs_analyzed = resp.json().get("docs_analyzed", 0)
    except Exception:
        try:
            r = _get_redis()
            docs_analyzed = int(r.get("forgensic:total_analyzed") or 0)
        except Exception:
            pass
    try:
        r = _get_redis()
        for key in r.scan_iter("forgensic:job:*"):
            raw = r.get(key)
            if raw:
                state = json.loads(raw)
                if state.get("status") in ("queued", "processing"):
                    active += 1
    except Exception:
        pass
    return {"docs_analyzed": docs_analyzed, "active_jobs": active}


@app.post("/api/token")
async def create_token(body: TokenRequest, request: Request) -> Dict[str, Any]:
    """Public token generation is disabled in production."""
    raise HTTPException(
        status_code=403,
        detail="Public token generation on this service is disabled. Developer tokens must be requested via the centralized /auth/token endpoint on session_logger with a verified Firebase ID token."
    )


@app.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    file: UploadFile = File(...),
    ocr_enabled: Optional[bool] = Form(None),
    _claims: Dict[str, Any] = Depends(require_bearer),
) -> JobCreateResponse:
    """
    Accept a document upload, persist it to the shared volume, and enqueue a
    Celery task.  Returns immediately with a job_id for polling.
    """
    _cleanup_jobs()

    if not file.filename or not _allowed_suffix(file.filename):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    job_id = uuid.uuid4().hex

    # Upload the input to GCS instead of a shared disk so a worker on any MIG VM
    # can fetch it. The worker downloads it, processes it, then deletes the object.
    file_bytes = await file.read()
    size = len(file_bytes)
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 25 MB limit")

    from forgensic.app.gcs_storage import upload_bytes  # noqa: PLC0415
    import mimetypes  # noqa: PLC0415
    content_type, _ = mimetypes.guess_type(file.filename)
    input_blob = f"forgensic/{job_id}/input/{file.filename}"
    try:
        input_gcs_uri = upload_bytes(file_bytes, input_blob, content_type)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upload input to GCS: {exc}")

    resolved_ocr = OCR_ENABLED if ocr_enabled is None else bool(ocr_enabled)

    # Write initial state to Redis *before* submitting the task so that
    # any immediate status poll doesn't get a 404.
    _write_job_state(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "progress": 0.0,
            "file_name": file.filename,
            "file_size": size,
            "ocr_enabled": resolved_ocr,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "pipeline_version": PIPELINE_VERSION,
        },
    )

    # Enqueue the Celery task — import lazily so the API starts even if the
    # broker is temporarily unavailable (health check will report degraded).
    from forgensic.tasks import process_forgensic_job  # noqa: PLC0415
    from common.metrics import DOCUMENTS_PROCESSED_TOTAL
    process_forgensic_job.apply_async(
        args=[job_id, input_gcs_uri, PIPELINE_PRESET, resolved_ocr],
        task_id=job_id,          # use job_id as Celery task ID for easy lookup
        queue="forgensic",
    )
    DOCUMENTS_PROCESSED_TOTAL.labels(service="forgensic").inc()

    return JobCreateResponse(job_id=job_id, status="queued", message="Job accepted")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    _claims: Dict[str, Any] = Depends(require_bearer),
) -> JobStatusResponse:
    state = _read_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job_id,
        status=state.get("status", "unknown"),
        progress=state.get("progress"),
        message=state.get("message"),
        created_at=state.get("created_at"),
        updated_at=state.get("updated_at"),
    )


@app.get("/jobs/{job_id}/results", response_model=JobResultResponse)
async def get_job_results(
    job_id: str,
    _claims: Dict[str, Any] = Depends(require_bearer),
) -> JobResultResponse:
    state = _read_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    if state.get("status") != "complete":
        raise HTTPException(status_code=404, detail="Results not ready")

    payload = state.get("result")
    if not payload:
        raise HTTPException(status_code=404, detail="Results not ready")

    return JobResultResponse(**payload)


@app.get("/jobs/{job_id}/files/{file_name}")
async def get_job_file(
    job_id: str,
    file_name: str,
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    """Serve a pipeline output file from GCS or the local volume."""
    state = _read_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    file_map: Dict[str, str] = state.get("file_map", {})
    location = file_map.get(file_name)
    if not location:
        raise HTTPException(status_code=404, detail="File not found")

    if location.startswith("gs://"):
        from forgensic.app.gcs_storage import download_bytes  # noqa: PLC0415
        try:
            data, content_type = download_bytes(location)
        except Exception:
            raise HTTPException(status_code=404, detail="File no longer available")
        if content_type is None:
            content_type, _ = mimetypes.guess_type(file_name)
        return Response(
            content=data,
            media_type=content_type or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{file_name}"'},
        )

    disk_path = Path(location)
    if not disk_path.exists():
        raise HTTPException(status_code=404, detail="File no longer available")

    content_type, _ = mimetypes.guess_type(str(disk_path))
    return FileResponse(
        path=str(disk_path),
        media_type=content_type or "application/octet-stream",
        filename=file_name,
    )
