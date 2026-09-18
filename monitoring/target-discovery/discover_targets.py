"""
monitoring/target-discovery/discover_targets.py

Writes a Prometheus file_sd target list by asking the GCE API which VMs are
currently in the `dpi-mig` instance group, every POLL_INTERVAL_SECONDS.

Why this exists: Prometheus's built-in gce_sd_config only supports one port
per discovery block, but our Celery workers publish multiple replicas' worth
of ports per VM (see docker-compose.yml's "9200-9203:9200" style ranges).
Rather than fight that with dozens of near-duplicate gce_sd_config blocks,
one small script here builds the full target list — API ports, node/queue
exporters, and all worker replica ports — for every VM currently in the
group, and Prometheus just watches the resulting file (file_sd_configs
auto-reloads on file change, no restart needed).

Auth: uses Application Default Credentials from the VM's attached service
account (no key file) — the same keyless pattern used elsewhere in this repo
(cloud-sql-proxy, GCS access in the app services). That service account needs
roles/compute.viewer on the project (see plan doc for the exact gcloud command).

Trade-off worth knowing: because worker ports are published as a fixed range
per replica slot rather than addressed by container name, the Prometheus
`instance` label for worker metrics becomes "<vm-ip>:<port>" instead of the
old "<container-name>". Still one distinct series per running replica —
dashboards that aggregate with sum()/rate() are unaffected — but it reads
less descriptively than the old container-name label if you look at it directly.
"""

import json
import logging
import os
import time

import google.auth
import google.auth.transport.requests
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("target-discovery")

PROJECT = os.getenv("GCE_PROJECT", "proj-dpi-shared")
REGION = os.getenv("GCE_REGION", "asia-south1")
MIG_NAME = os.getenv("GCE_MIG_NAME", "dpi-mig")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "/output/targets.json")

# Fixed per-VM ports. Single-instance-per-VM services use one port; workers
# publish one port per replica slot (see docker-compose.yml port ranges).
SINGLE_PORT_JOBS = {
    "pdf2abdm": 8000,
    "pdf2nhcx": 8001,
    "session_logger": 8002,
    "privacy_filter": 8003,
    "forgensic": 8004,
    "node_exporter": 9100,
    "queue_exporter": 9101,
}

WORKER_PORT_RANGES = {
    "celery_abdm_workers": range(9200, 9204),
    "celery_nhcx_workers": range(9210, 9214),
    "celery_forgensic_workers": range(9220, 9224),
    "celery_privacy_workers": range(9230, 9238),
}


def _get_access_token() -> str:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token


def _list_mig_instance_ips() -> list[dict]:
    """Return [{"name": ..., "internal_ip": ...}, ...] for every VM currently
    in the instance group, across every zone in REGION."""
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    instances = []

    # Regional MIGs can span multiple zones within the region; ask the
    # region-scoped instance-group-managers endpoint directly rather than
    # guessing zone names.
    list_url = (
        f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}"
        f"/regions/{REGION}/instanceGroupManagers/{MIG_NAME}/listManagedInstances"
    )
    resp = requests.post(list_url, headers=headers, timeout=10)
    resp.raise_for_status()
    managed = resp.json().get("managedInstances", [])

    for m in managed:
        if m.get("instanceStatus") != "RUNNING":
            continue
        instance_url = m["instance"]  # full URL, ends in .../zones/<zone>/instances/<name>
        parts = instance_url.split("/")
        zone, name = parts[-3], parts[-1]

        detail = requests.get(
            f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}"
            f"/zones/{zone}/instances/{name}",
            headers=headers,
            timeout=10,
        )
        detail.raise_for_status()
        nic = detail.json().get("networkInterfaces", [{}])[0]
        internal_ip = nic.get("networkIP")
        if internal_ip:
            instances.append({"name": name, "internal_ip": internal_ip})

    return instances


def build_targets(instances: list[dict]) -> list[dict]:
    groups = []

    for job, port in SINGLE_PORT_JOBS.items():
        targets = [f"{i['internal_ip']}:{port}" for i in instances]
        if targets:
            groups.append({"targets": targets, "labels": {"job": job}})

    for job, port_range in WORKER_PORT_RANGES.items():
        targets = [f"{i['internal_ip']}:{p}" for i in instances for p in port_range]
        if targets:
            groups.append({"targets": targets, "labels": {"job": job}})

    return groups


def main():
    logger.info(
        "target-discovery starting: project=%s region=%s mig=%s poll=%ds",
        PROJECT, REGION, MIG_NAME, POLL_INTERVAL,
    )
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    while True:
        try:
            instances = _list_mig_instance_ips()
            groups = build_targets(instances)
            tmp_path = OUTPUT_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(groups, f, indent=2)
            os.replace(tmp_path, OUTPUT_PATH)  # atomic — Prometheus never sees a half-written file
            logger.info("wrote %d target groups for %d instances", len(groups), len(instances))
        except Exception as e:
            logger.error("discovery cycle failed, keeping last-known-good targets file: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
