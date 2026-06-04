"""
Celery task definitions for the forgensic (Forgery Detection) service.

Each uploaded document becomes one `process_forgensic_job` task.
The task:
  1. Runs the full classical CV pipeline (CPU-bound, ~1–3 s per page)
  2. Writes structured progress + final result JSON into Redis
  3. Keeps processed images on the shared volume so the API can serve them

No imports from forgensic.app.main — only from forgensic.app.{pipeline,config,utils}
to avoid circular dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Optional

import redis as redis_lib

import httpx

from forgensic.celery_app import celery_app
from common.metrics import (
    TASKS_STARTED_TOTAL,
    TASKS_COMPLETED_TOTAL,
    TASKS_FAILED_TOTAL,
    TASK_DURATION_SECONDS,
    DOCUMENTS_FAILED_TOTAL,
)

logger = logging.getLogger(__name__)

SESSION_LOGGER_URL = os.getenv("SESSION_LOGGER_URL", "http://session-logger:8002")


def _fire_log(payload: dict):
    """POST a session log entry to the logger service. Never raises."""
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(f"{SESSION_LOGGER_URL}/log", json=payload)
    except Exception as exc:
        logger.warning("[session-logger] fire-and-forget failed: %s", exc)

# ── Redis helpers ──────────────────────────────────────────────────────────────

def _redis_client() -> redis_lib.Redis:
    """Return a Redis client from the REDIS_URL env var."""
    return redis_lib.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )


def _job_key(job_id: str) -> str:
    return f"forgensic:job:{job_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_job_state(job_id: str, payload: Dict[str, Any]) -> None:
    """Merge *payload* into the existing Redis hash for this job."""
    r = _redis_client()
    key = _job_key(job_id)
    ttl = int(os.getenv("JOB_TTL_SECONDS", "3600"))
    existing_raw = r.get(key)
    state: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {}
    state.update(payload)
    r.set(key, json.dumps(state, default=str), ex=ttl)


# ── The Task ───────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="forgensic.tasks.process_forgensic_job",
    max_retries=0,          # don't auto-retry — errors are user-visible
    acks_late=True,
)
def process_forgensic_job(
    self,
    job_id: str,
    file_path_str: str,
    preset: str,
    ocr_enabled: bool,
) -> Dict[str, Any]:
    """
    Run the forgery-detection pipeline for one document.

    Args:
        job_id:        UUID hex string identifying the job.
        file_path_str: Absolute path to the uploaded file on the shared volume.
        preset:        Pipeline tuning preset (e.g. 'npv_focus', 'super_loose').
        ocr_enabled:   Whether to run Tesseract OCR as part of the analysis.

    Returns:
        {"status": "success"|"error", "job_id": job_id, ...}
    """
    # Lazy imports — keep worker startup fast; pipeline is a heavy module
    from forgensic.app.config import (
        DATA_DIR,
        FINDINGS_MAX_PER_PAGE,
        FINDINGS_MIN_AREA_RATIO,
        PIPELINE_VERSION,
    )
    from forgensic.app.pipeline import build_findings_summary, run_pipeline
    from forgensic.app.utils import build_results_payload

    file_path = Path(file_path_str)
    job_dir = DATA_DIR / job_id
    output_dir = job_dir / "output"

    # ── 1. Mark as processing ─────────────────────────────────────────────────
    _write_job_state(
        job_id,
        {"status": "processing", "updated_at": _now_iso(), "progress": 0.05},
    )
    self.update_state(state="PROGRESS", meta={"progress": 0.05, "step": "starting"})
    TASKS_STARTED_TOTAL.labels(service="forgensic").inc()
    _task_start = perf_counter()

    try:
        # ── 2. Run the CV pipeline ────────────────────────────────────────────
        self.update_state(state="PROGRESS", meta={"progress": 0.1, "step": "pipeline"})
        _write_job_state(job_id, {"progress": 0.1})

        t0 = perf_counter()
        run_output = run_pipeline(file_path, job_dir, preset=preset, enable_ocr=ocr_enabled)
        inference_seconds = perf_counter() - t0

        pages = run_output["pages"]
        results = run_output["results"]
        export_info = run_output["export_info"]

        # ── 3. Build findings summary (light OCR pass for human-readable text) ─
        self.update_state(state="PROGRESS", meta={"progress": 0.85, "step": "findings"})
        _write_job_state(job_id, {"progress": 0.85})

        findings_summary = build_findings_summary(
            pages,
            results,
            max_per_page=FINDINGS_MAX_PER_PAGE,
            min_area_ratio=FINDINGS_MIN_AREA_RATIO,
        )

        avg_inference_seconds: Optional[float] = (
            inference_seconds / max(len(pages), 1) if pages else None
        )

        # ── 4. Build URL + disk-path maps ─────────────────────────────────────
        # Files live on the shared volume — the API reads them back from disk.
        # We store a file_map in Redis so the API can resolve name → disk path.
        file_map: Dict[str, str] = {}     # name → absolute disk path
        file_url_map: Dict[str, str] = {} # name → /jobs/{id}/files/{name}
        preview_url_map: Dict[str, str] = {}

        for page in pages:
            image_path = page.image_path or page.original_path
            if image_path and Path(image_path).exists():
                name = page.page_file_name
                file_map[name] = image_path
                file_url_map[name] = f"/jobs/{job_id}/files/{name}"

            if page.preview_path and Path(page.preview_path).exists():
                pname = Path(page.preview_path).name
                file_map[pname] = page.preview_path
                preview_url_map[page.page_file_name] = f"/jobs/{job_id}/files/{pname}"

        # Export artefacts (JSON, Excel, YAML annotations)
        for fname in ["submission.json", "submission_preview.xlsx"]:
            p = output_dir / fname
            if p.exists():
                file_map[fname] = str(p)
                file_url_map[fname] = f"/jobs/{job_id}/files/{fname}"

        for yaml_path_str in export_info.get("yaml_paths", []):
            yp = Path(yaml_path_str)
            if yp.exists():
                file_map[yp.name] = str(yp)
                file_url_map[yp.name] = f"/jobs/{job_id}/files/{yp.name}"

        # ── 5. Build the complete result payload ──────────────────────────────
        # Read created_at from the existing Redis record so we preserve it
        r = _redis_client()
        raw = r.get(_job_key(job_id))
        existing = json.loads(raw) if raw else {}
        created_at = existing.get("created_at")
        updated_at = _now_iso()

        payload = build_results_payload(
            job_id=job_id,
            file_name=file_path.name,
            pages=pages,
            results=results,
            export_info=export_info,
            file_url_map=file_url_map,
            preview_url_map=preview_url_map,
            pipeline_version=PIPELINE_VERSION,
            created_at=created_at,
            updated_at=updated_at,
            findings_summary=findings_summary,
            inference_seconds=inference_seconds,
            avg_inference_seconds=avg_inference_seconds,
        )

        # ── 6. Persist result + file_map to Redis ─────────────────────────────
        _write_job_state(
            job_id,
            {
                "status": "complete",
                "updated_at": updated_at,
                "progress": 1.0,
                "inference_seconds": inference_seconds,
                "avg_inference_seconds": avg_inference_seconds,
                "summary_text": (findings_summary or {}).get("summary_text"),
                "category_summary": payload.get("category_summary", {}),
                "result": payload,
                "file_map": file_map,
            },
        )

        # Increment global docs-analyzed counter (atomic)
        r.incr("forgensic:total_analyzed")

        _fire_log({
            "service": "forgensic",
            "ip_address": "unknown",
            "pdf_location": file_path.name,
        })

        # ── 7. Clean up the raw input file (output stays for serving) ─────────
        # Note: We no longer eagerly delete the input directory here.
        # Single-image uploads use the original file as the `image_path` for the frontend.
        # The entire job directory will be cleaned up by the API's _cleanup_jobs TTL check.

        _task_elapsed = perf_counter() - _task_start
        TASKS_COMPLETED_TOTAL.labels(service="forgensic").inc()
        TASK_DURATION_SECONDS.labels(service="forgensic").observe(_task_elapsed)
        logger.info(
            "Job %s completed in %.2fs (%d pages)",
            job_id, inference_seconds, len(pages),
        )
        return {"status": "success", "job_id": job_id}

    except Exception as exc:
        logger.exception("Pipeline error for job %s: %s", job_id, exc)
        TASKS_FAILED_TOTAL.labels(service="forgensic").inc()
        DOCUMENTS_FAILED_TOTAL.labels(service="forgensic").inc()
        _write_job_state(
            job_id,
            {"status": "error", "updated_at": _now_iso(), "message": str(exc)},
        )
        return {"status": "error", "job_id": job_id, "message": str(exc)}
