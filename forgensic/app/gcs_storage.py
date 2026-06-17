"""
gcs_storage.py — GCS helper for the forgensic (Forgery Detection) service.

Unlike ABDM/NHCX (whose only shared-disk dependency is the input PDF), forgensic
also produces OUTPUT artefacts (processed images, previews, JSON, Excel, YAML)
that the API serves back to the user. For the service to run behind the MIG load
balancer — where the API and the worker may live on different VMs — BOTH the
input and the output must live in GCS rather than on a local/shared disk.

Bucket layout (bucket: $GCS_BUCKET, default dpi-transient-processing)
────────────────────────────────────────────────────────────────────
  forgensic/<job_id>/input/<filename>     ← uploaded document (transient)
  forgensic/<job_id>/output/<name>        ← pipeline artefacts (served to user)

Output objects must survive until the job's Redis TTL elapses (JOB_TTL_SECONDS,
1 h by default) so the user can view results; the bucket's lifecycle rule is the
final safety net.

Auth priority mirrors the ABDM/NHCX helper:
  1. GCS_CREDENTIALS_JSON  → dedicated GCS SA
  2. GOOGLE_APPLICATION_CREDENTIALS → shared SA or ADC
  3. Plain ADC (GCP metadata server) ← used on the VM (sa-dpi-app-prod)
"""

import os
import logging
import mimetypes
import tempfile

logger = logging.getLogger(__name__)

GCS_BUCKET           = os.getenv("GCS_BUCKET", "dpi-transient-processing")
GCS_CREDENTIALS_JSON = os.getenv("GCS_CREDENTIALS_JSON", "")
GOOGLE_CREDENTIALS   = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")


def _get_gcs_client():
    """Return an authenticated GCS client."""
    from google.cloud import storage as gcs
    if GCS_CREDENTIALS_JSON and os.path.isfile(GCS_CREDENTIALS_JSON):
        logger.info(f"GCS: using dedicated GCS SA ({GCS_CREDENTIALS_JSON})")
        return gcs.Client.from_service_account_json(GCS_CREDENTIALS_JSON)
    if GOOGLE_CREDENTIALS and os.path.isfile(GOOGLE_CREDENTIALS):
        logger.info(f"GCS: using GOOGLE_APPLICATION_CREDENTIALS ({GOOGLE_CREDENTIALS})")
        return gcs.Client.from_service_account_json(GOOGLE_CREDENTIALS)
    logger.info("GCS: using Application Default Credentials (ADC)")
    return gcs.Client()


def parse_gcs_uri(gcs_uri: str):
    """Split a gs://bucket/path/to/blob URI into (bucket, blob_name)."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    path = gcs_uri[5:]
    bucket, blob = path.split("/", 1)
    return bucket, blob


# ── Uploads ───────────────────────────────────────────────────────────────────

def upload_bytes(file_bytes: bytes, blob_name: str, content_type: str | None = None) -> str:
    """
    Upload in-memory bytes to gs://$GCS_BUCKET/<blob_name>. Returns the gs:// URI.
    Raises on failure — the caller (API submit) must surface upload errors.
    """
    client = _get_gcs_client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_bytes, content_type=content_type or "application/octet-stream")
    gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
    logger.info(f"GCS upload successful: {gcs_uri}")
    return gcs_uri


def upload_file(local_path: str, blob_name: str, content_type: str | None = None) -> str | None:
    """
    Upload a local file to gs://$GCS_BUCKET/<blob_name>. Returns the gs:// URI, or
    None on failure (non-fatal — a single missing artefact degrades to a 404 on
    that one file, it shouldn't fail the whole job).
    """
    try:
        if content_type is None:
            content_type, _ = mimetypes.guess_type(local_path)
        client = _get_gcs_client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path, content_type=content_type or "application/octet-stream")
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info(f"GCS artefact uploaded: {gcs_uri}")
        return gcs_uri
    except Exception as e:
        logger.warning(f"GCS artefact upload failed (non-fatal) for {local_path}: {e}")
        return None


# ── Downloads ─────────────────────────────────────────────────────────────────

def download_to_path(gcs_uri: str, dest_path: str) -> str:
    """Download a GCS object to *dest_path* (creating parent dirs). Returns dest_path."""
    client = _get_gcs_client()
    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    blob = client.bucket(bucket_name).blob(blob_name)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    blob.download_to_filename(dest_path)
    logger.info(f"GCS object downloaded: {gcs_uri} -> {dest_path}")
    return dest_path


def download_bytes(gcs_uri: str):
    """
    Download a GCS object into memory. Returns (bytes, content_type).
    Used by the API to stream artefacts back to the client.
    """
    client = _get_gcs_client()
    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    blob = client.bucket(bucket_name).blob(blob_name)
    data = blob.download_as_bytes()
    return data, blob.content_type


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_gcs_object(gcs_uri: str) -> None:
    """Delete a single GCS object. Non-fatal — logs and swallows any error."""
    try:
        client = _get_gcs_client()
        bucket_name, blob_name = parse_gcs_uri(gcs_uri)
        client.bucket(bucket_name).blob(blob_name).delete()
        logger.info(f"GCS object deleted: {gcs_uri}")
    except Exception as e:
        logger.warning(f"Failed deleting GCS object {gcs_uri}: {e}")
