"""
Celery application for the forgensic (Forgery Detection) service.

Runs on a dedicated 'forgensic' queue — completely isolated from the
nhcx and abdm worker pools so CV workloads never starve insurance/clinical jobs.

Worker startup (docker-compose override):
    celery -A forgensic.celery_app worker --loglevel=info --concurrency=2 -Q forgensic
"""
import os
import logging

from celery import Celery
from celery.signals import task_retry, task_failure, worker_ready

logger = logging.getLogger(__name__)

from common.secrets import load_secrets
load_secrets()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "forgensic_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["forgensic.tasks"],
)

celery_app.conf.update(
    # ── Serialisation ─────────────────────────────────────────────────────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # ── Time zone ─────────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,

    # ── Reliability ───────────────────────────────────────────────────────────
    task_track_started=True,
    task_acks_late=True,           # Ack only after task completes — never lose a job on worker crash
    worker_prefetch_multiplier=1,  # Each worker only takes 1 task at a time (CV tasks are heavy)
    task_reject_on_worker_lost=True,  # Re-queue the task if a worker dies mid-execution

    # ── Timeouts ──────────────────────────────────────────────────────────────
    task_time_limit=3600,          # 1 h hard kill
    task_soft_time_limit=3300,     # 55 min soft — raises SoftTimeLimitExceeded, lets task clean up

    # ── Result backend ────────────────────────────────────────────────────────
    result_expires=3600,           # Keep Celery result entries for 1 h (matches JOB_TTL_SECONDS)

    # ── Routing ───────────────────────────────────────────────────────────────
    task_routes={
        "forgensic.tasks.process_forgensic_job": {"queue": "forgensic"},
    },
    task_default_queue="forgensic",
)

# ── Phase 5: Celery signal hooks for retry/exhaustion tracking ────────────────


@task_retry.connect
def on_task_retry(sender, request, reason, einfo, **kwargs):
    """Increment retry counter whenever a Celery task schedules a retry."""
    try:
        from common.metrics import TASK_RETRIES_TOTAL
        TASK_RETRIES_TOTAL.labels(service="forgensic").inc()
        logger.warning("task_retry service=forgensic task=%s reason=%s", sender.name, reason)
    except Exception:
        pass  # Signal handlers must never crash the worker


@task_failure.connect
def on_task_failure(sender, task_id, exception, traceback, einfo, **kwargs):
    """Increment retry-exhausted counter when MaxRetriesExceededError is raised."""
    try:
        if type(exception).__name__ == "MaxRetriesExceededError":
            from common.metrics import TASK_RETRY_EXHAUSTED_TOTAL
            TASK_RETRY_EXHAUSTED_TOTAL.labels(service="forgensic").inc()
            logger.error(
                "task_retry_exhausted service=forgensic task=%s task_id=%s",
                sender.name, task_id,
            )
    except Exception:
        pass


# ── Phase 5.8: Worker metrics HTTP server ─────────────────────────────────────


def _start_worker_metrics_server() -> None:
    """Start a Prometheus HTTP metrics server — see common/celery_app.py for details."""
    port_str = os.getenv("WORKER_METRICS_PORT")
    multiproc_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if not port_str or not multiproc_dir:
        return

    os.makedirs(multiproc_dir, exist_ok=True)

    from prometheus_client import CollectorRegistry, multiprocess as _mp
    from prometheus_client.exposition import make_wsgi_app
    from wsgiref.simple_server import make_server
    import threading

    port = int(port_str)

    def _serve():
        registry = CollectorRegistry()
        _mp.MultiProcessCollector(registry)
        app = make_wsgi_app(registry)
        httpd = make_server("0.0.0.0", port, app)
        httpd.serve_forever()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    logger.info("Worker metrics server started on :%d/metrics", port)


@worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    _start_worker_metrics_server()
