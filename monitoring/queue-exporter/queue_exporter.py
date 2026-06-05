"""
monitoring/queue-exporter/queue_exporter.py

Prometheus exporter that measures:
  1. Celery/Redis queue depths (Phase 3)
  2. Container restart counts via Docker socket (Phase 5)

Design decisions:
- Queue depths: LLEN on the raw Redis queue keys used by Celery.
- Container restarts: polls Docker socket (read-only) for RestartCount per container.
  The Docker restart count is a cumulative value; Prometheus `increase()` over a time
  window reveals restart spikes and crash loops in alert rules.
- Poll interval is configurable; defaults to 15s to match Prometheus scrape interval.
- Exposes a single /metrics endpoint on port 9101.

Why LLEN instead of Celery Inspect:
- Celery Inspect requires active workers to respond; LLEN is a pure Redis operation.
- LLEN is O(1), has negligible overhead, and never fails due to worker unavailability.

Queue key names (Celery default broker is Redis list):
  Celery uses `<queue-name>` as the Redis key for its task list.

Container restart monitoring:
  Reads `RestartCount` from the Docker container inspect endpoint.
  The Docker socket is mounted read-only from the host: /var/run/docker.sock.
  If Docker is unavailable, restart metrics are silently skipped (no false data).
"""

import os
import time
import logging

import redis
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("queue-exporter")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9101"))

# ── Queue depth configuration ─────────────────────────────────────────────────

QUEUES = ["abdm", "nhcx", "forgensic"]

queue_depth_gauge = Gauge(
    "dpi_queue_depth",
    "Current number of messages waiting in a Celery/Redis queue.",
    ["queue"],
)

# ── Container restart configuration ──────────────────────────────────────────

# Application containers to monitor for restarts.
# Monitoring-stack containers are included to detect infrastructure failures.
MONITORED_CONTAINERS = [
    # Application services
    "pdf2abdm",
    "pdf2nhcx",
    "privacy-filter",
    "forgensic",
    "session-logger",
    "redis",
    # Monitoring stack
    "prometheus",
    "alertmanager",
    "grafana",
    "loki",
    "promtail",
    "node-exporter",
    "queue-exporter",
]

container_restart_gauge = Gauge(
    "dpi_container_restart_count",
    "Cumulative restart count for a container as reported by Docker. "
    "Use increase() over a time window to detect restart spikes.",
    ["container"],
)

# ── Collection functions ──────────────────────────────────────────────────────


def _get_redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=False, socket_connect_timeout=3)


def collect_queue_depths():
    try:
        r = _get_redis_client()
        for queue_name in QUEUES:
            try:
                depth = r.llen(queue_name)
                queue_depth_gauge.labels(queue=queue_name).set(depth)
            except Exception as e:
                logger.warning("Failed to read queue %s: %s", queue_name, e)
                queue_depth_gauge.labels(queue=queue_name).set(-1)
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        for queue_name in QUEUES:
            queue_depth_gauge.labels(queue=queue_name).set(-1)


def collect_container_restarts():
    """Poll the Docker socket for container restart counts.

    Silently skips on Docker connectivity failure — queue depth metrics
    must not be blocked by Docker socket unavailability.
    """
    try:
        import docker
        docker_client = docker.from_env(timeout=5)
        for name in MONITORED_CONTAINERS:
            try:
                container = docker_client.containers.get(name)
                restart_count = container.attrs.get("RestartCount", 0)
                container_restart_gauge.labels(container=name).set(restart_count)
            except docker.errors.NotFound:
                # Container not running — skip; no stale value set
                pass
            except Exception as e:
                logger.warning("Failed to inspect container %s: %s", name, e)
        docker_client.close()
    except ImportError:
        # docker SDK not installed — Phase 5 container restart metrics unavailable
        logger.debug("docker SDK not available; skipping container restart metrics")
    except Exception as e:
        logger.warning("Docker connection failed; skipping container restart metrics: %s", e)


# ── Main loop ─────────────────────────────────────────────────────────────────


def main():
    logger.info("Queue + container-state exporter starting on port %d", METRICS_PORT)
    logger.info("Monitoring queues: %s", QUEUES)
    logger.info("Monitoring containers: %s", MONITORED_CONTAINERS)
    logger.info("Redis URL: %s", REDIS_URL)
    logger.info("Poll interval: %ds", POLL_INTERVAL)

    start_http_server(METRICS_PORT)
    logger.info("Metrics server started at :%d/metrics", METRICS_PORT)

    while True:
        collect_queue_depths()
        collect_container_restarts()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
