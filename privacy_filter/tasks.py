"""
privacy_filter/tasks.py — Celery background task for MedDeID redaction.

Flow:
  1. Read the uploaded file from the shared volume
  2. Run MedDeID de-identification (OCR + detection + redaction)
  3. Save redacted output to the shared volume
  4. Store result JSON in Redis (24 h TTL)
  5. Fire-and-forget log to session_logger
"""
import json
import logging
import os
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

import redis as redis_lib

from privacy_filter.celery_app import celery_app
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

RESULT_TTL = int(os.getenv("TASK_RESULT_TTL", 86400))
SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")


def _get_redis():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis_lib.from_url(url, decode_responses=True)


def _fire_log(payload: dict):
    try:
        import httpx
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{SESSION_LOGGER_URL}/log", json=payload)
    except Exception as exc:
        logger.warning("[session-logger] fire-and-forget failed: %s", exc)


@celery_app.task(
    bind=True,
    name="privacy_filter.tasks.process_redaction_task",
    max_retries=0,
    acks_late=True,
)
def process_redaction_task(
    self,
    job_id: str,
    upload_key: str,
    filename: str,
    content_type: str,
):
    task_id = self.request.id
    start_time = time.perf_counter()
    TASKS_STARTED_TOTAL.labels(service="privacy_filter").inc()

    def update(step: str, progress: int):
        self.update_state(
            state="PROGRESS",
            meta={"step": step, "progress": progress, "task_id": task_id},
        )

    try:
        update("Loading file", 10)

        from privacy_filter.app import service
        from privacy_filter.app.storage import get_storage, _guess_content_type

        storage = get_storage()

        upload_path = None
        for tmp_base in ["pf_uploads"]:
            p = Path(tempfile.gettempdir()) / tmp_base / upload_key
            if p.exists():
                upload_path = p
                break
        if upload_path is None:
            try:
                upload_path = storage.local_path("uploads", upload_key)
                if not upload_path.exists():
                    upload_path = None
            except Exception:
                pass
        if upload_path is None:
            raise FileNotFoundError(f"Upload file not found: {upload_key}")

        update("De-identifying", 30)
        out_ext = service.out_extension(filename)
        stem = Path(filename).stem
        redacted_key = f"{job_id}__{stem}_redacted{out_ext}"
        tmp_redact_dir = Path(tempfile.gettempdir()) / "pf_redacted"
        tmp_redact_dir.mkdir(parents=True, exist_ok=True)
        redacted_local = tmp_redact_dir / redacted_key

        entities_raw, counts, meta = service.run_deidentification(
            upload_path, redacted_local,
        )

        if not redacted_local.exists():
            raise RuntimeError("Engine completed but produced no output file.")

        update("Saving results", 80)

        with open(redacted_local, "rb") as fh:
            storage.save("redacted", redacted_key, fh.read())

        entities = [
            {
                "entity_group": e.get("entity_group", "PHI"),
                "score": e.get("score", 1.0),
                "word": e.get("word"),
                "start": e.get("start"),
                "end": e.get("end"),
                "bbox": e.get("bbox"),
            }
            for e in entities_raw
        ]

        notes = None
        if not meta.get("validation_passed", False):
            notes = (
                f"Validation risk score {meta.get('risk_score', 0)}. "
                f"{meta.get('notes') or ''}".strip()
            )

        result_payload = {
            "status": "completed",
            "task_id": task_id,
            "job_id": job_id,
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "entities": entities,
            "entity_counts": dict(Counter(counts)),
            "original_url": storage.url("uploads", upload_key),
            "redacted_url": storage.url("redacted", redacted_key),
            "text_preview_original": None,
            "text_preview_redacted": None,
            "notes": notes,
        }

        update("Storing results", 95)
        r = _get_redis()
        r.setex(f"pf:result:{task_id}", RESULT_TTL, json.dumps(result_payload))

        update("Completed", 100)
        elapsed = time.perf_counter() - start_time
        TASKS_COMPLETED_TOTAL.labels(service="privacy_filter").inc()
        TASK_DURATION_SECONDS.labels(service="privacy_filter").observe(elapsed)
        DOCUMENTS_PROCESSED_TOTAL.labels(service="privacy_filter").inc()
        logger.info("[%s] Privacy filter task completed in %.2fs", task_id, elapsed)

        _fire_log({
            "service": "privacy_filter",
            "ip_address": "unknown",
            "pdf_location": filename,
        })

        return result_payload

    except Exception as exc:
        logger.exception(
            "[%s] Privacy filter task failed exception_type=%s: %s",
            task_id, type(exc).__name__, exc,
        )
        TASKS_FAILED_TOTAL.labels(service="privacy_filter").inc()
        DOCUMENTS_FAILED_TOTAL.labels(service="privacy_filter").inc()
        record_exception("privacy_filter", exc)

        error_payload = {
            "status": "failed",
            "task_id": task_id,
            "job_id": job_id,
            "error": str(exc),
        }
        try:
            r = _get_redis()
            r.setex(f"pf:result:{task_id}", RESULT_TTL, json.dumps(error_payload))
        except Exception:
            pass
        raise
