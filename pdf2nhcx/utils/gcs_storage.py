"""
gcs_storage.py — GCS upload utility for NHCX Hackathon services

GCS folder layout (bucket: tanuh-bcd-bucket)
─────────────────────────────────────────────
  pdf_uploads/abdm/<filename>.pdf    ← uploaded PDFs (clinical)
  pdf_uploads/nhcx/<filename>.pdf    ← uploaded PDFs (insurance)
  json_output/abdm/<filename>.json   ← ABDM FHIR bundles
  json_output/nhcx/<filename>.json   ← NHCX insurance bundles

Auth priority:
  1. GCS_CREDENTIALS_JSON env var → dedicated SA for GCS (tanuh-bcd-application2)
  2. GOOGLE_APPLICATION_CREDENTIALS → shared SA or ADC
  3. Plain ADC (GCP metadata server)

Failures are non-fatal — main FHIR pipeline always completes.
"""

import os
import logging
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


# ── PDF uploads ───────────────────────────────────────────────────────────────

def upload_pdf_from_bytes(file_bytes: bytes, filename: str, gcs_folder: str) -> str | None:
    """
    Upload a PDF from in-memory bytes to GCS. No local file is written.

    Args:
        file_bytes: Raw bytes of the PDF.
        filename:   Destination filename inside the bucket folder.
        gcs_folder: e.g. 'pdf_uploads/abdm' or 'pdf_uploads/nhcx'.

    Returns:
        GCS URI string, or None if upload failed (non-fatal).
    """
    try:
        client    = _get_gcs_client()
        bucket    = client.bucket(GCS_BUCKET)
        blob_name = f"{gcs_folder.rstrip('/')}/{filename}"
        blob      = bucket.blob(blob_name)
        blob.upload_from_string(file_bytes, content_type="application/pdf")
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info(f"GCS PDF upload successful: {gcs_uri}")
        return gcs_uri
    except ImportError:
        logger.warning("google-cloud-storage not installed — skipping GCS PDF upload")
        return None
    except Exception as e:
        logger.warning(f"GCS PDF upload failed (non-fatal): {e}")
        return None


def upload_pdf_to_gcs(local_file_path: str, gcs_folder: str) -> str | None:
    """
    Upload a PDF from a local path to GCS.
    Kept for backward compat (used by pdf2nhcxurl which receives
    a path to a pre-existing file on the mounted volume).

    GCS folder convention:
        pdf_uploads/abdm/   for clinical documents
        pdf_uploads/nhcx/   for insurance documents
    """
    try:
        client    = _get_gcs_client()
        bucket    = client.bucket(GCS_BUCKET)
        filename  = os.path.basename(local_file_path)
        blob_name = f"{gcs_folder.rstrip('/')}/{filename}"
        blob      = bucket.blob(blob_name)
        blob.upload_from_filename(local_file_path, content_type="application/pdf")
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info(f"GCS PDF upload successful: {gcs_uri}")
        return gcs_uri
    except ImportError:
        logger.warning("google-cloud-storage not installed — skipping GCS upload")
        return None
    except Exception as e:
        logger.warning(f"GCS upload failed (non-fatal): {e}")
        return None


# ── JSON uploads ──────────────────────────────────────────────────────────────

def upload_json_to_gcs(json_data: dict, gcs_folder: str, filename: str) -> str | None:
    """
    Upload a JSON dictionary to GCS directly from memory. No local file is written.

    GCS folder convention:
        json_output/abdm/   for ABDM FHIR bundles
        json_output/nhcx/   for NHCX insurance bundles

    Args:
        json_data:  The Python dictionary to serialise and save.
        gcs_folder: Destination folder inside the bucket.
        filename:   The filename to save as (e.g. 'bundle.json').

    Returns:
        GCS URI string, or None if upload failed.
    """
    try:
        import json
        client    = _get_gcs_client()
        bucket    = client.bucket(GCS_BUCKET)
        blob_name = f"{gcs_folder.rstrip('/')}/{filename}"
        blob      = bucket.blob(blob_name)
        blob.upload_from_string(
            data=json.dumps(json_data, indent=2),
            content_type="application/json"
        )
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info(f"GCS JSON upload successful: {gcs_uri}")
        return gcs_uri
    except ImportError:
        logger.warning("google-cloud-storage not installed — skipping GCS JSON upload")
        return None
    except Exception as e:
        logger.warning(f"GCS JSON upload failed (non-fatal): {e}")
        return None


# ── GCS download / delete (worker side) ───────────────────────────────────────

def parse_gcs_uri(gcs_uri: str):
    """Split a gs://bucket/path/to/blob URI into (bucket, blob_name)."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    path = gcs_uri[5:]
    bucket, blob = path.split("/", 1)
    return bucket, blob


def download_pdf_from_gcs(gcs_uri: str) -> str:
    """
    Download a GCS object to a local temp file and return the temp path.

    Raises on failure — unlike the upload helpers, a download failure must fail
    the task because there is nothing to process without the input PDF.
    """
    client = _get_gcs_client()
    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    blob = client.bucket(bucket_name).blob(blob_name)
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    blob.download_to_filename(temp_path)
    logger.info(f"GCS PDF downloaded: {gcs_uri}")
    return temp_path


def delete_gcs_object(gcs_uri: str) -> None:
    """Delete a GCS object. Non-fatal — logs and swallows any error."""
    try:
        client = _get_gcs_client()
        bucket_name, blob_name = parse_gcs_uri(gcs_uri)
        client.bucket(bucket_name).blob(blob_name).delete()
        logger.info(f"GCS object deleted: {gcs_uri}")
    except Exception as e:
        logger.warning(f"Failed deleting GCS object {gcs_uri}: {e}")
