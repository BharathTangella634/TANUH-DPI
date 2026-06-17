import os
import logging

from celery import Celery
from celery.signals import task_retry, task_failure, worker_ready

logger = logging.getLogger(__name__)

from common.secrets import load_secrets
load_secrets()

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
    worker_prefetch_multiplier=1,  # Enable fair dispatching
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


# ── Phase 5.8: Worker metrics HTTP server ─────────────────────────────────────

def _start_worker_metrics_server() -> None:
    """
    Start a Prometheus HTTP metrics server on WORKER_METRICS_PORT (default: off).

    Uses prometheus_client's multiprocess mode (PROMETHEUS_MULTIPROC_DIR) so
    that metrics incremented in Celery's forked child processes are aggregated
    and served from the main worker process over HTTP.

    Both WORKER_METRICS_PORT and PROMETHEUS_MULTIPROC_DIR must be set via env
    vars — they are absent from the API service containers, so this function is
    a no-op there.
    """
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
