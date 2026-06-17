#!/usr/bin/env python3
"""
fetch_validator_jar.py — Download validator_cli.jar from GCS if missing or stub.

Called at container startup (entrypoint) to replace the Git LFS pointer with the
real 177 MB JAR from gs://dpi-transient-processing/dependencies/validator_cli.jar.

Skips download if the local file already exists and is > 1 MB (i.e. not a stub).
Uses ADC (VM service account) for auth — no key file needed.
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fetch_validator_jar")

GCS_BUCKET = os.getenv("VALIDATOR_GCS_BUCKET", "dpi-transient-processing")
GCS_BLOB = os.getenv("VALIDATOR_GCS_BLOB", "dependencies/validator_cli.jar")
LOCAL_PATHS = [
    "/app/pdf2abdm/app/validator_cli.jar",
    "/app/pdf2nhcx/app/validator_cli.jar",
]
MIN_VALID_SIZE = 1_000_000  # 1 MB — real JAR is ~177 MB


def _needs_download(path: str) -> bool:
    if not os.path.exists(path):
        return True
    return os.path.getsize(path) < MIN_VALID_SIZE


def fetch():
    targets = [p for p in LOCAL_PATHS if _needs_download(p)]
    if not targets:
        logger.info("validator_cli.jar already present and valid at all paths — skipping download")
        return True

    try:
        from google.cloud import storage as gcs
    except ImportError:
        logger.warning("google-cloud-storage not installed — cannot fetch validator JAR")
        return False

    try:
        client = gcs.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(GCS_BLOB)

        if not blob.exists():
            logger.error("Validator JAR not found in GCS: gs://%s/%s", GCS_BUCKET, GCS_BLOB)
            return False

        tmp_path = targets[0] + ".downloading"
        logger.info("Downloading gs://%s/%s (%s MB) ...",
                     GCS_BUCKET, GCS_BLOB,
                     f"{blob.size / 1_000_000:.0f}" if blob.size else "?")
        blob.download_to_filename(tmp_path)
        os.rename(tmp_path, targets[0])
        logger.info("Downloaded validator_cli.jar to %s", targets[0])

        for extra in targets[1:]:
            os.makedirs(os.path.dirname(extra), exist_ok=True)
            import shutil
            shutil.copy2(targets[0], extra)
            logger.info("Copied validator_cli.jar to %s", extra)

        return True

    except Exception as exc:
        logger.error("Failed to download validator JAR: %s", exc)
        return False


if __name__ == "__main__":
    success = fetch()
    sys.exit(0 if success else 1)
