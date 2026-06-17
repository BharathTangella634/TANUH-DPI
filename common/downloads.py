"""
downloads.py — Serve desktop executables from local disk.

Executables are copied from GCS to /opt/downloads/ once at VM boot
(see deploy/bootstrap-vm.sh). The container mounts this as /app/downloads/.
Files are served directly from disk — no GCS egress, no signed URLs, instant.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

LOCAL_DIR = Path(os.getenv("DOWNLOADS_LOCAL_DIR", "/app/downloads"))

ALLOWED_FILES = {
    # Clinical (ABDM) + Insurance (NHCX)
    "nhcx-extract-linux-x86_64.zip",
    "nhcx-extract-linux-aarch64.zip",
    "nhcx-extract-windows-x86_64.zip",
    "nhcx-extract-macos.zip",
    # Forgensic
    "ForgensicApp-ubuntu-latest.zip",
    "ForgensicApp-ubuntu-24.04-arm.zip",
    "ForgensicApp-windows-latest.zip",
    "ForgensicApp-macos-latest.zip",
    # Privacy Filter
    "pf-redact-linux-x86_64.zip",
    "pf-redact-linux-aarch64.zip",
    "pf-redact-windows-x86_64.zip",
    "pf-redact-macos.zip",
}


def get_local_path(filename: str) -> Path | None:
    """Return the local path if the file exists on disk, else None."""
    if filename not in ALLOWED_FILES:
        return None
    path = LOCAL_DIR / filename
    if path.is_file():
        return path
    return None


def list_available_downloads() -> list[dict]:
    """List executables available on local disk."""
    available = []
    for filename in sorted(ALLOWED_FILES):
        path = LOCAL_DIR / filename
        if path.is_file():
            size_bytes = path.stat().st_size
            available.append({
                "filename": filename,
                "size_mb": round(size_bytes / (1024 * 1024), 1),
                "url": f"/downloads/{filename}",
            })
    return available
