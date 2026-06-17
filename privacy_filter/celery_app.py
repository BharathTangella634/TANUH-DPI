"""
Celery application for the privacy-filter (MedDeID) service.

Runs on a dedicated 'privacy_filter' queue — isolated from nhcx, abdm, and
forgensic worker pools.

Worker startup (docker-compose override):
    celery -A privacy_filter.celery_app worker --loglevel=info --concurrency=2 -Q privacy_filter
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
    "privacy_filter_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["privacy_filter.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=3600,
    task_routes={
        "privacy_filter.tasks.process_redaction_task": {"queue": "privacy_filter"},
    },
    task_default_queue="privacy_filter",
)


@task_retry.connect
def on_task_retry(sender, request, reason, einfo, **kwargs):
    try:
        from common.metrics import TASK_RETRIES_TOTAL
        TASK_RETRIES_TOTAL.labels(service="privacy_filter").inc()
        logger.warning("task_retry service=privacy_filter task=%s reason=%s", sender.name, reason)
    except Exception:
        pass


@task_failure.connect
def on_task_failure(sender, task_id, exception, traceback, einfo, **kwargs):
    try:
        if type(exception).__name__ == "MaxRetriesExceededError":
            from common.metrics import TASK_RETRY_EXHAUSTED_TOTAL
            TASK_RETRY_EXHAUSTED_TOTAL.labels(service="privacy_filter").inc()
            logger.error(
                "task_retry_exhausted service=privacy_filter task=%s task_id=%s",
                sender.name, task_id,
            )
    except Exception:
        pass


def _start_worker_metrics_server() -> None:
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
