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
POST /api/submit                → async multipart upload; returns task_id (202) [auth required]
GET  /api/task-status/{task_id} → poll task progress
GET  /api/task-result/{task_id} → fetch completed result
GET  /api/files/{kind}/{key}    → download originals or redacted outputs      [auth required]
GET  /api/render-pages/{kind}/{key} → render document pages as images for preview
GET  /api/page-image/{key}/{page_num} → serve a rendered page image
POST /api/apply-redactions      → apply user-drawn redaction boxes            [auth required]
"""
from __future__ import annotations

import gc
import io
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from jose import jwt
from pydantic import BaseModel, EmailStr

# Resolve secrets (SECRET_KEY etc.) from Secret Manager before .auth/config read them.
from common.secrets import load_secrets
load_secrets()

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


_CLEANUP_TTL_SECONDS = int(os.getenv("PF_FILE_TTL_SECONDS", "1800"))  # 30 min default
_CLEANUP_INTERVAL_SECONDS = int(os.getenv("PF_CLEANUP_INTERVAL_SECONDS", "300"))  # 5 min

_CLEANUP_DIRS = [
    Path(tempfile.gettempdir()) / "pf_uploads",
    Path(tempfile.gettempdir()) / "pf_redacted",
    Path(tempfile.gettempdir()) / "pf_pages",
    Path("./data/uploads"),
    Path("./data/redacted"),
]


def _cleanup_old_files():
    """Background thread: delete files older than TTL from temp/data dirs and,
    when the GCS backend is active, from the privacy bucket too (30-min window)."""
    gcs_backend = os.getenv("STORAGE_BACKEND", "local").lower() == "gcs"
    while True:
        time.sleep(_CLEANUP_INTERVAL_SECONDS)
        cutoff = time.time() - _CLEANUP_TTL_SECONDS
        for d in _CLEANUP_DIRS:
            if not d.exists():
                continue
            for item in d.iterdir():
                try:
                    if item.is_file() and item.stat().st_mtime < cutoff:
                        item.unlink()
                    elif item.is_dir() and item.stat().st_mtime < cutoff:
                        import shutil
                        shutil.rmtree(item, ignore_errors=True)
                except Exception:
                    pass
        # GCS sweep — enforce the 30-min edit window in the privacy bucket. A GCS
        # lifecycle rule can't express sub-day TTLs, so we delete expired objects
        # here. Best-effort: never let it crash the cleanup loop.
        if gcs_backend:
            try:
                store = get_storage()
                if hasattr(store, "cleanup_expired"):
                    store.cleanup_expired(_CLEANUP_TTL_SECONDS)
            except Exception:
                logger.exception("GCS cleanup pass failed")
        logger.debug("File cleanup pass complete (TTL=%ds)", _CLEANUP_TTL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the engine so the first request is fast.
    try:
        service.engine_ready()
    except Exception:
        logger.exception("MedDeID engine failed to initialise at startup")
    t = threading.Thread(target=_cleanup_old_files, daemon=True)
    t.start()
    logger.info("File cleanup thread started (TTL=%ds, interval=%ds)",
                _CLEANUP_TTL_SECONDS, _CLEANUP_INTERVAL_SECONDS)
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

from common.metrics import instrument_fastapi
instrument_fastapi(app, service="privacy_filter")


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
            logger.exception(
                "De-identification failed exception_type=%s severity=ERROR: %s",
                type(e).__name__, e,
            )
            from common.metrics import DOCUMENTS_FAILED_TOTAL, record_exception
            DOCUMENTS_FAILED_TOTAL.labels(service="privacy_filter").inc()
            record_exception("privacy_filter", e)
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
        from common.metrics import DOCUMENTS_PROCESSED_TOTAL
        DOCUMENTS_PROCESSED_TOTAL.labels(service="privacy_filter").inc()

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


# ---------------------------------------------------------------------------
# Async submit + poll endpoints (Celery-backed)
# ---------------------------------------------------------------------------

@app.post("/api/submit", status_code=202)
async def submit_redaction(
    request: Request,
    file: UploadFile = File(...),
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    """Submit a file for background redaction. Returns 202 with task_id immediately."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if not service.is_supported(file.filename):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Supported: {', '.join(service.supported_extensions())}",
        )

    storage = get_storage()
    job_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename).name
    upload_key = f"{job_id}__{safe_name}"

    raw_bytes = await file.read()

    tmp_upload_dir = Path(tempfile.gettempdir()) / "pf_uploads"
    tmp_upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = tmp_upload_dir / upload_key
    upload_path.write_bytes(raw_bytes)

    storage.save("uploads", upload_key, raw_bytes)
    del raw_bytes

    from privacy_filter.tasks import process_redaction_task
    task = process_redaction_task.delay(
        job_id, upload_key, safe_name, file.content_type or "application/octet-stream",
    )
    logger.info("[submit] Task queued: %s for %s", task.id, safe_name)

    return JSONResponse(status_code=202, content={
        "task_id": task.id,
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/task-status/{task.id}",
        "result_url": f"/api/task-result/{task.id}",
        "message": "Processing started. Poll poll_url for updates.",
    })


@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """Poll the progress of a submitted redaction task."""
    from celery.result import AsyncResult
    from privacy_filter.celery_app import celery_app as _celery

    res = AsyncResult(task_id, app=_celery)
    state = res.state

    if state == "SUCCESS" or (res.ready() and not res.failed()):
        return JSONResponse(content={
            "task_id": task_id,
            "status": "completed",
            "result_url": f"/api/task-result/{task_id}",
        })

    if res.failed():
        return JSONResponse(content={
            "task_id": task_id,
            "status": "failed",
            "error": str(res.result),
        })

    info = res.info if isinstance(res.info, dict) else {}
    return JSONResponse(content={
        "task_id": task_id,
        "status": state,
        "step": info.get("step", "Pending"),
        "progress": info.get("progress", 0),
        "result_url": f"/api/task-result/{task_id}",
    })


@app.get("/api/task-result/{task_id}")
async def get_task_result(task_id: str):
    """Retrieve the result of a completed redaction task."""
    import json as _json
    import redis as _redis

    r = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    cached = r.get(f"pf:result:{task_id}")
    if cached:
        return JSONResponse(content=_json.loads(cached))

    from celery.result import AsyncResult
    from privacy_filter.celery_app import celery_app as _celery

    res = AsyncResult(task_id, app=_celery)
    if not res.ready():
        return JSONResponse(status_code=202, content={
            "task_id": task_id,
            "status": "processing",
            "message": "Task is still running.",
        })
    if res.failed():
        return JSONResponse(status_code=500, content={
            "task_id": task_id,
            "status": "failed",
            "error": str(res.result),
        })
    return JSONResponse(content=res.result)


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


# ---------------------------------------------------------------------------
# Visual preview: render document pages as images
# ---------------------------------------------------------------------------

_PAGE_RENDER_DIR = Path(tempfile.gettempdir()) / "pf_pages"
_PAGE_RENDER_DPI = 150


def _find_stored_file(kind: str, key: str, storage=None) -> Path | None:
    """Search all possible locations for a stored file."""
    if storage is None:
        storage = get_storage()
    for tmp_base in ["pf_uploads", "pf_redacted"]:
        p = Path(tempfile.gettempdir()) / tmp_base / key
        if p.exists():
            return p
    try:
        p = storage.local_path(kind, key)
        if p.exists():
            return p
    except Exception:
        pass
    return None


def _persist_pages_to_gcs(storage, key: str, out_dir: Path) -> None:
    """Mirror locally-rendered page PNGs into GCS so any VM can serve them.

    The MIG runs multiple VMs and the load balancer does not pin a client to a
    single instance, so a page rendered on VM-A must be retrievable on VM-B.
    Nothing preview-related is allowed to live only on one VM's local disk.
    """
    if os.getenv("STORAGE_BACKEND", "local").lower() != "gcs":
        return
    for png in sorted(out_dir.glob("page_*.png")):
        try:
            storage.save("pages", f"{key}/{png.name}", png.read_bytes())
        except Exception:
            logger.exception("failed to persist page %s to GCS", png.name)


def _render_document_pages(file_path: Path, key: str, storage=None) -> List[Dict[str, Any]]:
    """Convert a document to page images. Returns [{page, url, width, height}].

    Rendered page PNGs are also persisted to GCS (when STORAGE_BACKEND=gcs) so
    that /api/page-image can be served by any MIG VM — not just the one that ran
    the render. Requests are not pinned to a single instance.
    """
    if storage is None:
        storage = get_storage()
    out_dir = _PAGE_RENDER_DIR / key
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = file_path.suffix.lower()
    pages_info: List[Dict[str, Any]] = []

    if suffix == ".pdf":
        import fitz
        with fitz.open(file_path) as doc:
            for i, page in enumerate(doc):
                zoom = _PAGE_RENDER_DPI / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_path = out_dir / f"page_{i}.png"
                pix.save(str(img_path))
                pages_info.append({"page": i, "url": f"/api/page-image/{key}/{i}", "width": pix.width, "height": pix.height})

    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        from PIL import Image as PILImage
        img = PILImage.open(file_path).convert("RGB")
        img_path = out_dir / "page_0.png"
        img.save(img_path, "PNG")
        pages_info.append({"page": 0, "url": f"/api/page-image/{key}/0", "width": img.width, "height": img.height})

    elif suffix in {".dcm", ".dicom"}:
        import pydicom
        from PIL import Image as PILImage
        import numpy as np
        ds = pydicom.dcmread(str(file_path), force=True)
        try:
            arr = ds.pixel_array
            if arr.ndim == 2:
                norm = ((arr - arr.min()) / (arr.max() - arr.min() + 1e-9) * 255).astype(np.uint8)
                img = PILImage.fromarray(norm, "L").convert("RGB")
            else:
                img = PILImage.fromarray(arr).convert("RGB")
            img_path = out_dir / "page_0.png"
            img.save(img_path, "PNG")
            pages_info.append({"page": 0, "url": f"/api/page-image/{key}/0", "width": img.width, "height": img.height})
        except Exception:
            logger.warning("DICOM has no pixel data for preview")

    elif suffix == ".nii" or str(file_path).lower().endswith(".nii.gz"):
        try:
            import nibabel as nib
            from PIL import Image as PILImage
            import numpy as np
            nii = nib.load(str(file_path))
            data = np.asanyarray(nii.dataobj)
            if data.ndim >= 3:
                mid_slice = data[:, :, data.shape[2] // 2]
            else:
                mid_slice = data
            norm = ((mid_slice - mid_slice.min()) / (mid_slice.max() - mid_slice.min() + 1e-9) * 255).astype(np.uint8)
            img = PILImage.fromarray(norm, "L").convert("RGB")
            img_path = out_dir / "page_0.png"
            img.save(img_path, "PNG")
            pages_info.append({"page": 0, "url": f"/api/page-image/{key}/0", "width": img.width, "height": img.height})
        except Exception:
            logger.warning("NIfTI preview failed")

    _persist_pages_to_gcs(storage, key, out_dir)
    return pages_info


@app.get("/api/render-pages/{kind}/{key}")
async def render_pages(
    kind: str, key: str,
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    if kind not in {"uploads", "redacted"}:
        raise HTTPException(status_code=404, detail="Unknown kind")
    storage = get_storage()
    file_path = _find_stored_file(kind, key, storage)
    if file_path is None:
        raise HTTPException(status_code=404, detail="File not found")
    pages = _render_document_pages(file_path, key, storage)
    return {"pages": pages, "text_only": False}


@app.get("/api/page-image/{key}/{page_num}")
async def page_image(key: str, page_num: int):
    img_path = _PAGE_RENDER_DIR / key / f"page_{page_num}.png"
    if img_path.exists():
        return FileResponse(img_path, media_type="image/png")
    # MIG/multi-VM: the page may have been rendered on a different VM. The render
    # step mirrors pages to GCS, so retrieve it from there rather than 404-ing.
    if os.getenv("STORAGE_BACKEND", "local").lower() == "gcs":
        try:
            data = get_storage().open_read("pages", f"{key}/page_{page_num}.png")
            return StreamingResponse(data, media_type="image/png")
        except Exception:
            logger.warning("page-image %s/%s not found in GCS", key, page_num)
    raise HTTPException(status_code=404, detail="Page image not found")


# ---------------------------------------------------------------------------
# Apply user-drawn redaction boxes
# ---------------------------------------------------------------------------

class ApplyRedactionsRequest(BaseModel):
    job_id: str
    source_key: str
    boxes: List[Dict[str, Any]]
    image_width: int
    image_height: int


@app.post("/api/apply-redactions")
async def apply_redactions(
    body: ApplyRedactionsRequest,
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    storage = get_storage()
    tmp_upload = _find_stored_file("uploads", body.source_key, storage)
    if tmp_upload is None:
        raise HTTPException(status_code=404, detail="Original file not found")

    suffix = tmp_upload.suffix.lower()
    original_name = body.source_key.split("__", 1)[-1] if "__" in body.source_key else body.source_key
    out_ext = Path(original_name).suffix.lower() or suffix

    redacted_key = f"{body.job_id}__redacted_edited{out_ext}"
    tmp_redact_dir = Path(tempfile.gettempdir()) / "pf_redacted"
    tmp_redact_dir.mkdir(parents=True, exist_ok=True)
    redacted_path = tmp_redact_dir / redacted_key

    try:
        if suffix == ".pdf":
            _apply_boxes_pdf(tmp_upload, body.boxes, body.image_width, body.image_height, redacted_path)
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            _apply_boxes_image(tmp_upload, body.boxes, body.image_width, body.image_height, redacted_path, suffix)
        elif suffix in {".dcm", ".dicom"}:
            _apply_boxes_dicom(tmp_upload, body.boxes, body.image_width, body.image_height, redacted_path)
        else:
            raise HTTPException(status_code=415, detail=f"Editing not supported for {suffix}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("apply-redactions failed")
        raise HTTPException(status_code=500, detail=str(e))

    with open(redacted_path, "rb") as fh:
        storage.save("redacted", redacted_key, fh.read())

    preview_pages = _render_document_pages(redacted_path, redacted_key)
    return {
        "redacted_key": redacted_key,
        "redacted_url": storage.url("redacted", redacted_key),
        "preview_pages": preview_pages,
    }


def _apply_boxes_pdf(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path):
    import fitz
    doc = fitz.open(src)
    for box in boxes:
        page_idx = int(box.get("page", 0))
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        sx, sy = pw / img_w, ph / img_h
        rect = fitz.Rect(box["x"] * sx, box["y"] * sy, (box["x"] + box["w"]) * sx, (box["y"] + box["h"]) * sy)
        page.add_redact_annot(rect, fill=(0, 0, 0))
    for page in doc:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    doc.save(str(out), garbage=4, deflate=True, clean=True)
    doc.close()


def _apply_boxes_image(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path, suffix: str = ".png"):
    from PIL import Image as PILImage, ImageDraw
    img = PILImage.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    sx, sy = img.width / img_w, img.height / img_h
    for box in boxes:
        draw.rectangle([box["x"] * sx, box["y"] * sy, (box["x"] + box["w"]) * sx, (box["y"] + box["h"]) * sy], fill=(0, 0, 0))
    if suffix in {".jpg", ".jpeg"}:
        img.save(out, "JPEG", quality=95)
    elif suffix in {".tif", ".tiff"}:
        img.save(out, "TIFF")
    elif suffix == ".bmp":
        img.save(out, "BMP")
    else:
        img.save(out, "PNG")


def _apply_boxes_dicom(src: Path, boxes: List[Dict], img_w: int, img_h: int, out: Path):
    import pydicom
    import numpy as np
    ds = pydicom.dcmread(str(src), force=True)
    try:
        arr = ds.pixel_array.copy()
    except Exception:
        raise HTTPException(status_code=415, detail="DICOM has no pixel data")
    h_actual, w_actual = arr.shape[0], arr.shape[1] if arr.ndim >= 2 else 1
    sx, sy = w_actual / img_w, h_actual / img_h
    for box in boxes:
        y0, y1 = max(0, int(box["y"] * sy)), min(h_actual, int((box["y"] + box["h"]) * sy))
        x0, x1 = max(0, int(box["x"] * sx)), min(w_actual, int((box["x"] + box["w"]) * sx))
        arr[y0:y1, x0:x1, ...] = 0 if arr.ndim == 2 else 0
    ds.PixelData = arr.tobytes()
    ds.save_as(str(out), write_like_original=False)


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
