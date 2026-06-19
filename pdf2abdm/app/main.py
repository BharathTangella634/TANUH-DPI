import os
import sys
import argparse
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import shutil
import time

import subprocess
import json
import re
import uuid
import httpx
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Any, Dict

from common.secrets import load_secrets
load_secrets()

from pdf2abdm.app.auth import require_bearer, issue_demo_token, log_token_to_session_logger

# ── Session Logger integration ────────────────────────────────────────────────
SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")

def _fire_log(payload: dict):
    """Send a log payload to session_logger. Called in a BackgroundTask — never raises."""
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{SESSION_LOGGER_URL}/log", json=payload)
    except Exception as exc:
        # Silently swallow — logging must never break the inference response
        print(f"[session-logger] fire-and-forget failed: {exc}")

class LocalFileRequest(BaseModel):
    file_path: str
    model: str = "gemma4"
    ocr_engine: str = "auto"

# ── PDF Upload Limits ────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 25
MAX_PAGE_COUNT   = 100

def validate_pdf_upload(file_path: str):
    """Raise HTTPException 413 if the PDF exceeds size or page limits."""
    import os
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail={
                "title": "File Too Large",
                "message": f"The uploaded PDF is {size_mb:.1f} MB. Maximum allowed size is {MAX_FILE_SIZE_MB} MB."
            }
        )
    try:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        page_count = len(reader.pages)
        if page_count > MAX_PAGE_COUNT:
            raise HTTPException(
                status_code=413,
                detail={
                    "title": "Too Many Pages",
                    "message": f"The uploaded PDF has {page_count} pages. Maximum allowed is {MAX_PAGE_COUNT} pages."
                }
            )
    except HTTPException:
        raise
    except Exception:
        pass  # If page counting fails, let the pipeline handle it


def validate_pdf_bytes(file_bytes: bytes):
    """In-memory equivalent of validate_pdf_upload (size / page limits).

    Used by the async submit endpoint, which uploads straight to GCS and never
    writes the PDF to a local/shared disk. Raises HTTPException 413 on violation.
    """
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail={
                "title": "File Too Large",
                "message": f"The uploaded PDF is {size_mb:.1f} MB. Maximum allowed size is {MAX_FILE_SIZE_MB} MB."
            }
        )
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        page_count = len(reader.pages)
        if page_count > MAX_PAGE_COUNT:
            raise HTTPException(
                status_code=413,
                detail={
                    "title": "Too Many Pages",
                    "message": f"The uploaded PDF has {page_count} pages. Maximum allowed is {MAX_PAGE_COUNT} pages."
                }
            )
    except HTTPException:
        raise
    except Exception:
        pass  # If page counting fails, let the pipeline handle it

# Add the parent directory to sys.path to allow importing from utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.ocr_engine import extract_text_from_abdm_pdf, classify_document
# from utils.fhir_converter import convert_diagnostic_report_to_fhir, convert_discharge_summary_to_fhir
from utils.llm_requirements import run_abdm_pipeline

from utils.logger import get_logger
from common.classifier import classify_document_text, keyword_screen

logger = get_logger(__name__)

async def get_abdm_json(pdf_path, model: str = "gemma4"):
    try:
        filename = os.path.basename(pdf_path)
        logger.info(f"Processing {filename}...")
        
        # Perform OCR
        unique_patients_text_list, pdf_base64 = await extract_text_from_abdm_pdf(pdf_path)

        # ── Document-type gate ────────────────────────────────────────────────
        # Check the merged text (all pages combined) before running the
        # expensive FHIR pipeline.  Reject non-clinical documents early.
        combined_text = "\n".join(unique_patients_text_list)
        doc_category = await classify_document_text(combined_text)
        logger.info(f"Document category for {filename}: {doc_category}")

        if doc_category != "CLINICAL":
            if doc_category == "INSURANCE":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "title": "Wrong Service",
                        "message": (
                            "This document appears to be an insurance/NHCX document. "
                            "Please upload it using the NHCX tab instead."
                        ),
                        "detected_type": "INSURANCE",
                    },
                )
            raise HTTPException(
                status_code=422,
                detail={
                    "title": "Invalid Document",
                    "message": (
                        "The uploaded PDF does not appear to be a clinical medical record "
                        "(e.g. discharge summary, lab report, diagnostic report). "
                        "Please upload a valid clinical document."
                    ),
                    "detected_type": doc_category,
                },
            )
        # ─────────────────────────────────────────────────────────────────────

        import concurrent.futures
        import asyncio

        def process_patient(i, extracted_text):
            # Classify Document
            doc_type, must_resources, selected_other_resources = classify_document(extracted_text)
            logger.info(f"Patient {i}: Document classified as: {doc_type}")
            print(f"Patient {i}: Document classified as: {doc_type}")

            # Process and upload to GCS
            bundle = run_abdm_pipeline(
                extracted_text, doc_type, selected_other_resources,
                pdf_base64=pdf_base64, idx=i,
                model=model
            )
            return bundle, doc_type

        bundles = []
        doc_types = []
        
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            tasks = [
                loop.run_in_executor(executor, process_patient, i, extracted_text)
                for i, extracted_text in enumerate(unique_patients_text_list)
            ]
            results = await asyncio.gather(*tasks)

        for bundle, doc_type in results:
            bundles.append(bundle)
            doc_types.append(doc_type)

        logger.info(f"Successfully processed {filename} with {len(bundles)} patients concurrently.")
        return bundles, doc_types

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing {pdf_path}: {e}")




# ---------------------------------------------------------------------------
# OpenAPI 3.0 metadata
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ABDM FHIR Extraction API",
    description=(
        "Production-grade OCR and FHIR extraction pipeline for clinical documents.\n\n"
        "## Authentication\n"
        "Protected endpoints require a **Bearer token**.\n"
        "1. Call `POST /api/token` with your name and email to receive a 7-day JWT.\n"
        "2. Pass it as `Authorization: Bearer <token>` on all processing requests.\n\n"
        "Set `ABDM_AUTH_ENABLED=false` to bypass auth in local development."
    ),
    version="3.0.0",
    docs_url="/docs",
    contact={"name": "TANUH AI", "url": "https://tanuh.ai", "email": "nhcx@tanuh.ai"},
    license_info={"name": "Proprietary", "url": "https://tanuh.ai"},
    openapi_tags=[
        {"name": "Auth", "description": "Token issuance endpoints."},
        {"name": "Status", "description": "Health and system status endpoints."},
        {"name": "Processing", "description": "Core document processing endpoints (Bearer token required)."},
    ],
)


def custom_openapi():
    """Inject OpenAPI 3.0 securitySchemes so Swagger UI shows the Authorize button."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "HS256 JWT issued by POST /api/token (demo) or Keycloak (production).",
        }
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

from common.rate_limit import RateLimitMiddleware, RequestIDMiddleware, register_standard_error_handlers

app.add_middleware(RequestIDMiddleware)
register_standard_error_handlers(app)

app.add_middleware(
    RateLimitMiddleware,
    service_name="pdf2abdm",
    limit=150
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from common.metrics import instrument_fastapi
instrument_fastapi(app, service="pdf2abdm")

from pdf2abdm.tasks import process_abdm_task
from celery.result import AsyncResult

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Auth endpoint
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    name: str
    email: EmailStr


@app.post("/api/token", tags=["Auth"], summary="Request a demo bearer token")
async def create_token(body: TokenRequest, request: Request):
    """Public token generation is disabled in production."""
    raise HTTPException(
        status_code=403,
        detail="Public token generation on this service is disabled. Developer tokens must be requested via the centralized /auth/token endpoint on session_logger with a verified Firebase ID token."
    )


# Alias so Apache proxy can route /pdf2abdm/api/token → this app without stripping prefix
@app.post("/pdf2abdm/api/token", tags=["Auth"], include_in_schema=False)
async def create_token_prefixed(body: TokenRequest, request: Request):
    raise HTTPException(
        status_code=403,
        detail="Public token generation on this service is disabled. Developer tokens must be requested via the centralized /auth/token endpoint on session_logger with a verified Firebase ID token."
    )


# ---------------------------------------------------------------------------
# Health endpoints (public — no auth)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Status"], summary="Check API health")
@app.get("/pdf2abdm/health", tags=["Status"], include_in_schema=False)
@app.get("/pdf2fhir/health", tags=["Status"], include_in_schema=False)
def health_check():
    """Lightweight liveness probe — always 200 if the service started."""
    return {"status": "ok", "service": "pdf2abdm"}

@app.get("/model-health", tags=["Status"], summary="Check LLM model availability")
@app.get("/pdf2abdm/model-health", tags=["Status"], include_in_schema=False)
@app.get("/pdf2fhir/model-health", tags=["Status"], include_in_schema=False)
def model_health(model: str = "gemma4"):
    """Returns 200 if the model name is recognised (gemma4). Auth is validated at inference time."""
    from utils.llm_requirements import MODEL_MAP
    if model not in MODEL_MAP:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "reason": "unknown_model", "model": model}
        )
    return {"status": "ok", "model": model, "vertex_model": MODEL_MAP[model]}

@app.get("/ocr-health", tags=["Status"], summary="Check OCR engine availability")
@app.get("/pdf2abdm/ocr-health", tags=["Status"], include_in_schema=False)
@app.get("/pdf2fhir/ocr-health", tags=["Status"], include_in_schema=False)
def ocr_health(engine: str = "lighton"):
    """Check if a specific OCR engine is available."""
    KNOWN_ENGINES = {"lighton", "suriya", "chandra", "docling"}
    if engine not in KNOWN_ENGINES:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "reason": "unknown_engine", "engine": engine}
        )
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
        return {"status": "ok", "engine": engine}
    except ImportError:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "reason": "docling_unavailable", "engine": engine}
        )


@app.post("/pdf2abdm", tags=["Processing"], summary="Convert PDF to ABDM FHIR Bundle (Sync)")
async def convert_pdf_to_abdm(
    file: UploadFile = File(...),
    model: str = Form("gemma4"),
    ocr_engine: str = Form("auto"),
    state: str = Form(None),
    city: str = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    request: Request = None,
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    filename = file.filename.replace(" ", "_")
    logger.info(f"Received PDF upload: {filename}")
    session_id = str(uuid.uuid4())
    client_ip = request.client.host if request else None

    file_bytes = await file.read()

    # Temp file for OCR engine (needs a path, auto-deleted after)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    log_payload = {
        "service": "pdf2abdm",
        "ip_address": client_ip or "unknown",
        "state": state,
        "city": city,
    }
    try:
        from common.metrics import DOCUMENTS_PROCESSED_TOTAL, DOCUMENTS_FAILED_TOTAL
        validate_pdf_upload(tmp_path)
        start_time = time.perf_counter()
        result = await get_abdm_json(tmp_path, model=model)
        bundles, doc_types = result if result else ([], [])
        processing_time = round(time.perf_counter() - start_time, 2)
        if bundles and doc_types:
            log_payload["json_location"] = f"json_output/abdm/FHIR_BUNDLE_{doc_types[0]}_Patient_0.json"
            DOCUMENTS_PROCESSED_TOTAL.labels(service="pdf2abdm").inc()
        else:
            DOCUMENTS_FAILED_TOTAL.labels(service="pdf2abdm").inc()
    except Exception as exc:
        DOCUMENTS_FAILED_TOTAL.labels(service="pdf2abdm").inc()
        raise
    finally:
        os.unlink(tmp_path)
        background_tasks.add_task(_fire_log, log_payload)

    logger.info(f"get_abdm_json execution time: {processing_time} seconds")
    return JSONResponse(content={
        "processing_time": f"{processing_time} seconds",
        "document_type": ", ".join(doc_types) if doc_types else "Unknown",
        "bundles": bundles,
        "bundle_names": [f"Bundle {i+1} - {doc_types[i] if i < len(doc_types) else 'Unknown'}" for i in range(len(bundles))],
        "model_used": model,
        "ocr_engine_used": ocr_engine,
    })

@app.post("/pdf2abdmurl", tags=["Processing"], summary="Convert local PDF to ABDM FHIR Bundle via file path")
async def convert_pdf_to_abdm_url(body: LocalFileRequest, background_tasks: BackgroundTasks = BackgroundTasks()):
    file_path = body.file_path
    model = body.model
    ocr_engine = body.ocr_engine
    session_id = str(uuid.uuid4())

    if not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"message": f"File not found: {file_path}"})

    logger.info(f"Received local PDF request for: {file_path}")
    validate_pdf_upload(file_path)

    filename = os.path.basename(file_path)
    log_payload = {
        "service": "pdf2abdm",
        "ip_address": "unknown",
    }
    try:
        start_time = time.perf_counter()
        result = await get_abdm_json(file_path, model=model)
        bundles, doc_types = result if result else ([], [])
        processing_time = round(time.perf_counter() - start_time, 2)
        if bundles and doc_types:
            log_payload["json_location"] = f"json_output/abdm/FHIR_BUNDLE_{doc_types[0]}_Patient_0.json"
    except Exception as exc:
        raise
    finally:
        background_tasks.add_task(_fire_log, log_payload)

    logger.info(f"get_abdm_json execution time: {processing_time} seconds")
    return JSONResponse(content={
        "processing_time": f"{processing_time} seconds",
        "document_type": ", ".join(doc_types) if doc_types else "Unknown",
        "bundles": bundles,
        "bundle_names": [f"Bundle {i+1} - {doc_types[i] if i < len(doc_types) else 'Unknown'}" for i in range(len(bundles))],
        "model_used": model,
        "ocr_engine_used": ocr_engine,
    })

# ── Async Submit: file upload ────────────────────────────────────────────────
@app.post("/pdf2abdm/submit", tags=["Processing"],
          summary="Submit PDF upload for async ABDM processing",
          status_code=202)
async def submit_abdm(
    file: UploadFile = File(...),
    model: str = Form("gemma4"),
    _claims: Dict[str, Any] = Depends(require_bearer),
):
    """
    Submit a PDF for background processing. Returns a `task_id` immediately.
    Poll `GET /task-status/{task_id}` for progress.
    Fetch the result from `GET /task-result/{task_id}` when completed.
    Typical processing time: 3–8 minutes.
    """
    filename = file.filename.replace(" ", "_")

    file_bytes = await file.read()

    # Validate in-memory (size / page count) before touching GCS, so the 413
    # guard still applies without writing to a shared volume.
    validate_pdf_bytes(file_bytes)

    # Upload to GCS instead of a shared disk so a worker on any MIG VM can fetch
    # it. The worker downloads it from the returned gs:// URI, then deletes it.
    from utils.gcs_storage import upload_pdf_from_bytes
    import uuid as _uuid

    gcs_filename = f"{_uuid.uuid4().hex}_{filename}"
    gcs_uri = upload_pdf_from_bytes(
        file_bytes=file_bytes,
        filename=gcs_filename,
        gcs_folder="pdf_uploads/abdm",
    )
    if not gcs_uri:
        raise HTTPException(status_code=500, detail="Failed to upload PDF to GCS")

    task = process_abdm_task.delay(gcs_uri, model=model)
    logger.info(f"ABDM task queued: {task.id} for {filename}")
    return JSONResponse(status_code=202, content={
        "task_id": task.id,
        "status": "queued",
        "poll_url": f"/pdf2abdm/task-status/{task.id}",
        "result_url": f"/pdf2abdm/task-result/{task.id}",
        "message": "Processing started. Poll poll_url every 5–10 s for updates.",
    })


# ── Async Submit: local file path ────────────────────────────────────────────
@app.post("/pdf2abdm/submit-url", tags=["Processing"],
          summary="Submit local PDF path for async ABDM processing",
          status_code=202)
async def submit_abdm_url(request: LocalFileRequest):
    """
    Same as /pdf2abdm/submit but accepts a JSON body with a `file_path` pointing
    to a file already accessible inside the container (e.g. mounted volume).
    """
    file_path = request.file_path
    if not os.path.exists(file_path):
        return JSONResponse(status_code=404,
                            content={"message": f"File not found: {file_path}"})
    validate_pdf_upload(file_path)
    task = process_abdm_task.delay(file_path, model=request.model)
    logger.info(f"ABDM task queued (url): {task.id} for {file_path}")
    return JSONResponse(status_code=202, content={
        "task_id": task.id,
        "status": "queued",
        "poll_url": f"/pdf2abdm/task-status/{task.id}",
        "result_url": f"/pdf2abdm/task-result/{task.id}",
        "message": "Processing started. Poll poll_url every 5–10 s for updates.",
    })


# ── Task Status (enhanced) ────────────────────────────────────────────────────
@app.get("/task-status/{task_id}", tags=["Processing"],
         summary="Poll the status of a submitted task")
@app.get("/pdf2abdm/task-status/{task_id}", include_in_schema=False)
async def get_task_status(task_id: str):
    """
    Returns the current status of a background task.

    States:
    - `queued`    — task is waiting for a worker
    - `STARTED`   — worker picked it up
    - `PROGRESS`  — running (includes step + progress 0–100)
    - `completed` — finished; call GET /task-result/{task_id}
    - `failed`    — task raised an exception
    """
    res = AsyncResult(task_id, app=process_abdm_task.app)
    state = res.state

    if state == "SUCCESS" or (res.ready() and not res.failed()):
        return JSONResponse(content={
            "task_id": task_id,
            "status": "completed",
            "result_url": f"/pdf2abdm/task-result/{task_id}",
        })

    if res.failed():
        return JSONResponse(status_code=200, content={
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
        "result_url": f"/pdf2abdm/task-result/{task_id}",
    })


# ── Task Result ───────────────────────────────────────────────────────────────
@app.get("/task-result/{task_id}", tags=["Processing"],
         summary="Retrieve the result of a completed task")
@app.get("/pdf2abdm/task-result/{task_id}", include_in_schema=False)
async def get_task_result(task_id: str):
    """
    Returns 200 + bundle JSON if the task is complete.
    Returns 202 if still processing.
    Returns 404 if task is unknown or result has expired (24 h TTL).
    """
    import redis as _redis
    r = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                        decode_responses=True)
    raw = r.get(f"result:{task_id}")
    if raw is None:
        # Also check Celery state in case Redis result key not yet written
        res = AsyncResult(task_id, app=process_abdm_task.app)
        if not res.ready():
            return JSONResponse(status_code=202, content={
                "task_id": task_id, "status": "processing",
                "message": "Task is still running. Try again shortly.",
            })
        return JSONResponse(status_code=404, content={
            "task_id": task_id,
            "message": "Result not found. It may have expired (24 h TTL) or the task ID is invalid.",
        })

    import json as _json
    payload = _json.loads(raw)
    if payload.get("status") == "failed":
        return JSONResponse(status_code=500, content=payload)
    return JSONResponse(content=payload)


# ── Legacy async endpoint (kept for backward compat) ─────────────────────────
@app.post("/pdf2abdm-async", tags=["Processing"],
          summary="[DEPRECATED] Use /pdf2abdm/submit instead",
          deprecated=True)
async def convert_pdf_to_abdm_async_legacy(
    file: UploadFile = File(...),
    model: str = Form("gemma4"),
):
    """Deprecated. Use POST /pdf2abdm/submit."""
    return await submit_abdm(file=file, model=model)


@app.post("/validate")
async def validate_fhir(request: Request):
    # 1. Receive data from the frontend
    body = await request.json()
    json_content = body.get("json_data")
    
    # 2. Create a unique temporary file to validate
    # This prevents multiple users from overwriting the same file
    temp_file = f"validate_{uuid.uuid4()}.json"
    
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(json_content)

            # 3. Run the HL7 Validator command
        # Compute absolute path for the JAR so that it works regardless of cwd
        validator_jar = os.path.join(BASE_DIR, "validator_cli.jar")
        if not os.path.exists(validator_jar):
            logger.error(f"Validator JAR not found at {validator_jar}")
            return {"report": "Error @ System: validator_cli.jar not found"}

        cmd = [
            "/usr/bin/java", "-Xmx2G", "-jar", validator_jar,
            temp_file,
            "-version", "4.0.1",
            "-ig", "nrces.in.ndhm#6.0.0"
        ]

        process = subprocess.run(cmd, capture_output=True, text=True)
        raw_output = process.stdout

        # 4. Clean the output using your regex logic
        # Remove ANSI color codes
        clean = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', raw_output)

        # Extract only the Error lines
        errors = []
        for line in clean.splitlines():
            line = line.strip()
            if line.startswith("Error @"):
                errors.append(line)

        # 5. Return the cleaned string back to the frontend
        return {"report": "\n".join(errors)}

    except Exception as e:
        return {"report": f"Error @ System: Failed to run validator. {str(e)}"}
        
    finally:
        # 6. Delete the temporary file
        if os.path.exists(temp_file):
            os.remove(temp_file)

# ── Desktop executable downloads (served from local disk) ────────────────────

@app.get("/downloads/{filename}", tags=["Downloads"],
         summary="Download a desktop executable")
async def download_executable(filename: str):
    """Serve executable from local disk (mounted from /opt/downloads on host)."""
    from common.downloads import get_local_path, ALLOWED_FILES
    from fastapi.responses import FileResponse

    if filename not in ALLOWED_FILES:
        return JSONResponse(status_code=404, content={"detail": "File not found"})

    path = get_local_path(filename)
    if path is None:
        return JSONResponse(status_code=404, content={"detail": "File not available — VM may still be downloading executables"})

    return FileResponse(
        path=str(path),
        media_type="application/zip",
        filename=filename,
    )


@app.get("/downloads", tags=["Downloads"],
         summary="List available desktop executables")
async def list_downloads():
    from common.downloads import list_available_downloads
    return {"downloads": list_available_downloads()}


def main():
    parser = argparse.ArgumentParser(description="OCR PDF to ABDM FHIR Converter (Local)")
    parser.add_argument("input", help="Path to input PDF file or directory")
    # parser.add_argument("--output_dir", help="Directory to save FHIR JSON results", default="fhir_results")
    # parser.add_argument("--md_dir", help="Directory to save intermediate Markdown results", default=None)
    
    args = parser.parse_args()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Go up 2 levels to get to NHCX_HACKATHON root
    # Level 1: pdf2abdm
    # Level 2: NHCX_HACKATHON
    repo_root = os.path.dirname(os.path.dirname(current_dir))
    
    # 3. Define the relative root for results
    # Path: .../NHCX_HACKATHON/fhir_results
    relative_root = os.path.join(repo_root, "fhir_results")
    
    # 4. Extract clean filename (e.g., "Test 1")
    file_name_only = os.path.splitext(os.path.basename(args.input))[0]
    
    # 5. Create path: .../NHCX_HACKATHON/fhir_results/Test 1/
    target_output_dir = os.path.join(relative_root, file_name_only)
    os.makedirs(target_output_dir, exist_ok=True)
    

    if os.path.isfile(args.input):
        start_time = time.perf_counter()   # ⏱ Start timer
        
        import asyncio
        bundle = asyncio.run(get_abdm_json(args.input, target_output_dir))
        
        end_time = time.perf_counter()     # ⏱ End timer
        total_time = end_time - start_time
        
        print(f"\n⏱ get_abdm_json execution time: {total_time:.2f} seconds")
        
    else:
        logger.error(f"Error: {args.input} is not a valid file or directory")
        sys.exit(1)

if __name__ == "__main__":
    main()

# import os
# import sys
# import argparse

# # Add the parent directory to sys.path to allow importing from utils
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from utils.ocr_engine import extract_text_from_pdf, classify_document
# from utils.fhir_converter import convert_diagnostic_report_to_fhir, convert_discharge_summary_to_fhir
# from utils.logger import get_logger

# logger = get_logger(__name__)

# def process_pdf(pdf_path, output_dir=None, md_dir=None):
#     try:
#         filename = os.path.basename(pdf_path)
#         logger.info(f"Processing {filename}...")

#         # Perform OCR
#         extracted_text = extract_text_from_pdf(pdf_path)

#         # Classify Document
#         doc_type = classify_document(extracted_text)
#         logger.info(f"Document classified as: {doc_type}")
#         print(f"Document classified as: {doc_type}")

#         # Save intermediate Markdown if requested
#         if md_dir:
#             if not os.path.exists(md_dir):
#                 os.makedirs(md_dir)
#             md_path = os.path.join(md_dir, f"{os.path.splitext(filename)[0]}_{doc_type}.md")
#             with open(md_path, "w") as f:
#                 f.write(extracted_text)
#             logger.info(f"Saved intermediate markdown to {md_path}")

#         # Convert to FHIR
#         if doc_type == "discharge_summary":
#             fhir_json, regex_data, llm_json = convert_discharge_summary_to_fhir(extracted_text, filename)
#         else:
#             fhir_json, regex_data, llm_json = convert_diagnostic_report_to_fhir(extracted_text, filename)

#         # Save result
#         if output_dir:
#             if not os.path.exists(output_dir):
#                 os.makedirs(output_dir)
#             output_path = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}_{doc_type}_fhir.json")
#             with open(output_path, "w") as f:
#                 f.write(fhir_json)
#             logger.info(f"Successfully processed {filename} and saved to {output_path}")

#             # Save LLM output separately if generated
#             if llm_json:
#                 llm_output_path = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}_{doc_type}_llm.json")
#                 with open(llm_output_path, "w") as f:
#                     f.write(llm_json)
#                 logger.info(f"Saved LLM generated FHIR JSON for {filename} to {llm_output_path}")

#             # Save Regex output separately
#             regex_output_path = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}_{doc_type}_regex.json")
#             import json
#             with open(regex_output_path, "w") as f:
#                 json.dump(regex_data, f, indent=2)
#             logger.info(f"Saved Regex extraction for {filename} to {regex_output_path}")
#         else:
#             logger.info(f"Successfully processed {filename}. Result:")
#             print(fhir_json)
#             print("Regex Extracted Data:")
#             import json
#             print(json.dumps(regex_data, indent=2))

#     except Exception as e:
#         logger.exception(f"Error processing {pdf_path}: {e}")

# def main():
#     parser = argparse.ArgumentParser(description="OCR PDF to ABDM FHIR Converter (Local)")
#     parser.add_argument("input", help="Path to input PDF file or directory")
#     parser.add_argument("--output_dir", help="Directory to save FHIR JSON results", default="fhir_results")
#     parser.add_argument("--md_dir", help="Directory to save intermediate Markdown results", default=None)

#     args = parser.parse_args()

#     if os.path.isfile(args.input):
#         process_pdf(args.input, args.output_dir, args.md_dir)
#     elif os.path.isdir(args.input):
#         for file in os.listdir(args.input):
#             if file.lower().endswith(".pdf"):
#                 process_pdf(os.path.join(args.input, file), args.output_dir, args.md_dir)
#     else:
#         logger.error(f"Error: {args.input} is not a valid file or directory")
#         sys.exit(1)

# if __name__ == "__main__":
#     main()

