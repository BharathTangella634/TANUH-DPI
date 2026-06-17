"""
pdf2abdm/tasks.py — Dedicated Celery background task for ABDM (Clinical) processing.

Flow:
  1. OCR the PDF (Docling waterfall)
  2. Classify document type
  3. Run ABDM pipeline (generates FHIR bundles)
  4. Store results in Redis under key  result:<task_id>  with 24 h TTL
  5. Fire-and-forget log to session_logger service
"""

import os
import sys
import asyncio
import json
import logging
import time
import uuid

# Ensure the app root is on the path so sibling imports work inside the worker
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Add pdf2abdm/ so bare `from utils.xxx` imports resolve (matches main.py behaviour)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.celery_app import celery_app
from common.metrics import (
    TASKS_STARTED_TOTAL,
    TASKS_COMPLETED_TOTAL,
    TASKS_FAILED_TOTAL,
    TASK_DURATION_SECONDS,
    DOCUMENTS_PROCESSED_TOTAL,
    DOCUMENTS_FAILED_TOTAL,
    record_exception,
)

logger = logging.getLogger(__name__)

RESULT_TTL = int(os.getenv("TASK_RESULT_TTL", 86400))   # 24 h
SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")


def _get_redis():
    """Return a redis.Redis client using the same URL as Celery."""
    import redis as _redis
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return _redis.from_url(url, decode_responses=True)


def _fire_log(payload: dict):
    """POST a session log entry to the logger service. Never raises."""
    try:
        import httpx
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{SESSION_LOGGER_URL}/log", json=payload)
    except Exception as exc:
        logger.warning(f"[session-logger] fire-and-forget failed: {exc}")


@celery_app.task(bind=True, name="pdf2abdm.tasks.process_abdm_task",
                 queue="abdm",
                 time_limit=1800, soft_time_limit=1740)
def process_abdm_task(self, pdf_path: str, model: str = "gemma4"):
    """
    Async Celery task for ABDM FHIR bundle generation.
    Returns a result dict that is also cached in Redis for /task-result/{task_id}.
    """
    from utils.gcs_storage import download_pdf_from_gcs, delete_gcs_object

    task_id = self.request.id
    session_id = str(uuid.uuid4())

    # pdf_path may be a gs:// URI (async submit) or a local path (submit-url /
    # legacy). Download GCS objects to a local temp file so the rest of the
    # pipeline is unchanged. pdf_location keeps the original ref so the finally
    # block can delete the GCS object after processing.
    pdf_location = pdf_path
    if pdf_location.startswith("gs://"):
        pdf_path = download_pdf_from_gcs(pdf_location)

    task_filename = os.path.basename(pdf_path)
    start_time = time.perf_counter()
    TASKS_STARTED_TOTAL.labels(service="pdf2abdm").inc()

    def update(step: str, progress: int):
        self.update_state(state="PROGRESS",
                          meta={"step": step, "progress": progress,
                                "task_id": task_id})

    log_payload = {
        "service": "pdf2abdm",
        "ip_address": "unknown",
    }

    try:
        # ── Step 1: OCR ──────────────────────────────────────────────────────
        update("OCR", 15)
        from utils.ocr_engine import extract_text_from_abdm_pdf, classify_document
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        unique_patients_text_list, pdf_base64 = loop.run_until_complete(
            extract_text_from_abdm_pdf(pdf_path)
        )

        # ── Step 2: Validate document type (gate) ────────────────────────────
        from common.classifier import classify_document_sync
        combined_text = "\n".join(unique_patients_text_list)
        doc_category = classify_document_sync(combined_text)
        logger.info(f"[{task_id}] Document category: {doc_category}")

        if doc_category != "CLINICAL":
            if doc_category == "INSURANCE":
                error_msg = (
                    "Wrong service: this document appears to be an insurance/NHCX document. "
                    "Please resubmit via the NHCX pipeline."
                )
            else:
                error_msg = (
                    "Invalid document: the uploaded PDF is not a clinical medical record "
                    "(discharge summary, lab report, diagnostic report). "
                    "Please upload a valid clinical document."
                )
            error_payload = {
                "status": "rejected",
                "task_id": task_id,
                "error": error_msg,
                "detected_type": doc_category,
            }
            r = _get_redis()
            r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(error_payload))
            logger.warning(f"[{task_id}] Document rejected: {doc_category}")
            return error_payload

        # ── Step 3: Classify resource type & Extract ──────────────────────────
        from utils.llm_requirements import run_abdm_pipeline

        bundles = []
        doc_types = []

        total = len(unique_patients_text_list)
        for i, extracted_text in enumerate(unique_patients_text_list):
            progress_pct = 20 + int((i / max(total, 1)) * 70)
            update(f"LLM Extraction — patient {i+1}/{total}", progress_pct)

            doc_type, must_resources, selected_other_resources = classify_document(extracted_text)
            logger.info(f"[{task_id}] Patient {i}: {doc_type}")

            bundle = run_abdm_pipeline(
                extracted_text, doc_type, selected_other_resources,
                pdf_base64=pdf_base64, idx=i, model=model
            )
            bundles.append(bundle)
            doc_types.append(doc_type)


        # ── Step 3: Store result in Redis ────────────────────────────────────
        update("Storing results", 95)
        processing_time = round(time.perf_counter() - start_time, 2)
        result_payload = {
            "status": "completed",
            "task_id": task_id,
            "doc_types": doc_types,
            "bundle_count": len(bundles),
            "bundles": bundles,
            "model_used": model,
        }
        r = _get_redis()
        r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(result_payload))

        log_payload.update({
            "pdf_location": f"pdf_uploads/abdm/{task_filename}",
        })

        update("Completed", 100)
        elapsed = time.perf_counter() - start_time
        TASKS_COMPLETED_TOTAL.labels(service="pdf2abdm").inc()
        TASK_DURATION_SECONDS.labels(service="pdf2abdm").observe(elapsed)
        DOCUMENTS_PROCESSED_TOTAL.labels(service="pdf2abdm").inc()
        logger.info(f"[{task_id}] ABDM task completed — {len(bundles)} bundle(s)")
        return result_payload

    except Exception as exc:
        logger.exception(
            "[%s] ABDM task failed exception_type=%s severity=%s: %s",
            task_id, type(exc).__name__,
            "CRITICAL" if "connection" in type(exc).__name__.lower() or "timeout" in type(exc).__name__.lower() else "ERROR",
            exc,
        )
        TASKS_FAILED_TOTAL.labels(service="pdf2abdm").inc()
        DOCUMENTS_FAILED_TOTAL.labels(service="pdf2abdm").inc()
        record_exception("pdf2abdm", exc)
        error_payload = {"status": "failed", "task_id": task_id, "error": str(exc)}
        try:
            r = _get_redis()
            r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(error_payload))
        except Exception:
            pass
        log_payload["pdf_location"] = f"pdf_uploads/abdm/{task_filename}"
        log_payload["processing_time_note"] = str(exc)
        raise

    finally:
        # Always attempt to log — success or failure
        _fire_log(log_payload)
        # Clean up the local temp file (downloaded from GCS, or shared-volume
        # temp for legacy/submit-url paths).
        try:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
        except Exception:
            pass
        # Delete the transient GCS object so nothing persists in the bucket.
        if pdf_location.startswith("gs://"):
            delete_gcs_object(pdf_location)
