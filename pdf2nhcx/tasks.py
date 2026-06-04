"""
pdf2nhcx/tasks.py — Dedicated Celery background task for NHCX (Insurance) processing.

Flow:
  1. OCR the PDF (Docling waterfall)
  2. Classify / select NHCX resources
  3. Run NHCX insurance pipeline (generates bundle)
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.celery_app import celery_app
from common.metrics import (
    TASKS_STARTED_TOTAL,
    TASKS_COMPLETED_TOTAL,
    TASKS_FAILED_TOTAL,
    TASK_DURATION_SECONDS,
    DOCUMENTS_PROCESSED_TOTAL,
    DOCUMENTS_FAILED_TOTAL,
)

logger = logging.getLogger(__name__)

RESULT_TTL = int(os.getenv("TASK_RESULT_TTL", 86400))   # 24 h
SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")


def _get_redis():
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


@celery_app.task(bind=True, name="pdf2nhcx.tasks.process_nhcx_task",
                 queue="nhcx",
                 time_limit=1800, soft_time_limit=1740)
def process_nhcx_task(self, pdf_path: str, model: str = "gemma4"):
    """
    Async Celery task for NHCX insurance bundle generation.
    Returns a result dict that is also cached in Redis for /task-result/{task_id}.
    """
    task_id = self.request.id
    session_id = str(uuid.uuid4())
    task_filename = os.path.basename(pdf_path)
    start_time = time.perf_counter()
    TASKS_STARTED_TOTAL.labels(service="pdf2nhcx").inc()

    def update(step: str, progress: int):
        self.update_state(state="PROGRESS",
                          meta={"step": step, "progress": progress,
                                "task_id": task_id})

    log_payload = {
        "service": "pdf2nhcx",
        "ip_address": "unknown",
    }

    try:
        # ── Step 1: OCR (raw text only — fast) ──────────────────────────────
        update("OCR", 10)
        from pdf2nhcx.utils.ocr_engine import extract_raw_text_from_nhcx_pdf, select_nhcx_resources
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        raw_text, pdf_base64 = loop.run_until_complete(
            extract_raw_text_from_nhcx_pdf(pdf_path)
        )

        # ── Step 2: Fast pre-classification on raw OCR text ──────────────────
        # Runs BEFORE distillation so wrong document types are rejected
        # immediately (seconds) instead of after 8 expensive LLM calls (~10 min).
        update("Classifying document", 20)
        from common.classifier import classify_document_sync
        doc_category = classify_document_sync(raw_text)
        logger.info(f"[{task_id}] Pre-classification result: {doc_category}")

        if doc_category != "INSURANCE":
            if doc_category == "CLINICAL":
                error_msg = (
                    "Wrong service: this document appears to be a clinical medical record "
                    "(discharge summary, lab report, etc.). "
                    "Please resubmit via the ABDM/Clinical pipeline tab."
                )
            else:
                error_msg = (
                    "Invalid document: the uploaded PDF does not appear to be an insurance document "
                    "(health insurance policy, NHCX claim, pre-authorization form). "
                    "Please upload a valid insurance document."
                )
            error_payload = {
                "status": "rejected",
                "task_id": task_id,
                "error": error_msg,
                "detected_type": doc_category,
            }
            r = _get_redis()
            r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(error_payload))
            logger.warning(f"[{task_id}] Document rejected early (pre-distillation): {doc_category}")
            return error_payload

        # ── Step 3: Distil insurance text (expensive: 8 LLM calls) ──────────
        # Only reached if the document is confirmed INSURANCE.
        update("Distilling insurance text", 35)
        from pdf2nhcx.utils.ocr_engine import distill_insurance_text
        distilled_text = distill_insurance_text(raw_text)

        # ── Step 4: Select NHCX resource types ──────────────────────────────
        update("Selecting FHIR resources", 50)
        doc_type, must_resources, selected_other_resources = select_nhcx_resources(distilled_text)
        logger.info(f"[{task_id}] Document type: {doc_type}")

        # ── Step 5: NHCX Pipeline (LLM extraction) ───────────────────────────
        update("LLM Extraction", 65)
        from pdf2nhcx.utils.llm_requirements import run_nhcx_insurance_pipeline

        bundle = run_nhcx_insurance_pipeline(
            distilled_text, doc_type, selected_other_resources,
            pdf_base64=pdf_base64, idx=0, model=model
        )

        # ── Step 4: Store result in Redis ─────────────────────────────────────
        update("Storing results", 95)
        processing_time = round(time.perf_counter() - start_time, 2)

        result_payload = {
            "status": "completed",
            "task_id": task_id,
            "doc_type": doc_type,
            "bundle": bundle,
            "model_used": model,
        }
        r = _get_redis()
        r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(result_payload))

        log_payload.update({
            "pdf_location": f"pdf_uploads/nhcx/{task_filename}",
        })

        update("Completed", 100)
        elapsed = time.perf_counter() - start_time
        TASKS_COMPLETED_TOTAL.labels(service="pdf2nhcx").inc()
        TASK_DURATION_SECONDS.labels(service="pdf2nhcx").observe(elapsed)
        DOCUMENTS_PROCESSED_TOTAL.labels(service="pdf2nhcx").inc()
        logger.info(f"[{task_id}] NHCX task completed")
        return result_payload

    except Exception as exc:
        logger.exception(f"[{task_id}] NHCX task failed: {exc}")
        TASKS_FAILED_TOTAL.labels(service="pdf2nhcx").inc()
        DOCUMENTS_FAILED_TOTAL.labels(service="pdf2nhcx").inc()
        error_payload = {"status": "failed", "task_id": task_id, "error": str(exc)}
        try:
            r = _get_redis()
            r.setex(f"result:{task_id}", RESULT_TTL, json.dumps(error_payload))
        except Exception:
            pass
        log_payload["pdf_location"] = f"pdf_uploads/nhcx/{task_filename}"
        raise

    finally:
        # Always attempt to log — success or failure
        _fire_log(log_payload)
        # Clean up the shared-volume temp file (written by the API container)
        try:
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
        except Exception:
            pass
