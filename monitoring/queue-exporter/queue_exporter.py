"""
monitoring/queue-exporter/queue_exporter.py

Lightweight Prometheus exporter that measures Celery/Redis queue depths.

Design decisions:
- Uses LLEN (list length) on the raw Redis queue keys used by Celery.
- Poll interval is configurable; defaults to 15s to match Prometheus scrape interval.
- Exposes a single /metrics endpoint on port 9101.
- No state — every scrape re-reads Redis.

Why LLEN instead of Celery Inspect:
- Celery Inspect requires active workers to respond; LLEN is a pure Redis operation.
- LLEN is O(1), has negligible overhead, and never fails due to worker unavailability.
- Cardinality: `queue` label has exactly 3 values (abdm, nhcx, forgensic) — safe.

Queue key names (Celery default broker is Redis list):
  Celery uses `<queue-name>` as the Redis key for its task list.
"""

import os
import time
import logging

import redis
from prometheus_client import start_http_server, Gauge, REGISTRY
from prometheus_client.core import CollectorRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("queue-exporter")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9101"))

# Queues to monitor — matches the Celery queue names in docker-compose.yml
QUEUES = ["abdm", "nhcx", "forgensic"]

queue_depth_gauge = Gauge(
    "dpi_queue_depth",
    "Current number of messages waiting in a Celery/Redis queue.",
    ["queue"],
)


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


def main():
    logger.info("Queue exporter starting on port %d", METRICS_PORT)
    logger.info("Monitoring queues: %s", QUEUES)
    logger.info("Redis URL: %s", REDIS_URL)
    logger.info("Poll interval: %ds", POLL_INTERVAL)

    start_http_server(METRICS_PORT)
    logger.info("Metrics server started at :%d/metrics", METRICS_PORT)

    while True:
        collect_queue_depths()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
