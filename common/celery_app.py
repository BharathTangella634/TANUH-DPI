import os
import logging

from celery import Celery
from celery.signals import task_retry, task_failure

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "nhcx_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["common.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    # ── Route tasks to dedicated queues ───────────────────────────────────────────
    # nhcx-workers listen on 'nhcx' queue; abdm-workers listen on 'abdm' queue.
    # This keeps insurance and clinical workloads fully isolated.
    task_routes={
        "pdf2nhcx.tasks.process_nhcx_task": {"queue": "nhcx"},
        "pdf2abdm.tasks.process_abdm_task": {"queue": "abdm"},
    },
    task_default_queue="nhcx",  # safety net for any unrouted task
)

# ── Phase 5: Celery signal hooks for retry/exhaustion tracking ────────────────


def _service_from_task_name(task_name: str) -> str:
    """Extract service label from a Celery task module path."""
    if task_name.startswith("pdf2abdm"):
        return "pdf2abdm"
    if task_name.startswith("pdf2nhcx"):
        return "pdf2nhcx"
    if task_name.startswith("forgensic"):
        return "forgensic"
    return task_name.split(".")[0]


@task_retry.connect
def on_task_retry(sender, request, reason, einfo, **kwargs):
    """Increment retry counter whenever a Celery task schedules a retry."""
    try:
        from common.metrics import TASK_RETRIES_TOTAL
        service = _service_from_task_name(sender.name)
        TASK_RETRIES_TOTAL.labels(service=service).inc()
        logger.warning(
            "task_retry service=%s task=%s reason=%s",
            service, sender.name, reason,
        )
    except Exception:
        pass  # Signal handlers must never crash the worker


@task_failure.connect
def on_task_failure(sender, task_id, exception, traceback, einfo, **kwargs):
    """Increment retry-exhausted counter when MaxRetriesExceededError is raised."""
    try:
        exc_name = type(exception).__name__
        if exc_name == "MaxRetriesExceededError":
            from common.metrics import TASK_RETRY_EXHAUSTED_TOTAL
            service = _service_from_task_name(sender.name)
            TASK_RETRY_EXHAUSTED_TOTAL.labels(service=service).inc()
            logger.error(
                "task_retry_exhausted service=%s task=%s task_id=%s",
                service, sender.name, task_id,
            )
    except Exception:
        pass
