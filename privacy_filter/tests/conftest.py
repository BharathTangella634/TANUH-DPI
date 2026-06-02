"""
conftest.py — shared pytest fixtures for the privacy_filter (MedDeID) suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent
DATA = ROOT / "data"

# ── sample file fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sample_dicom():
    """Back-compat alias for older unit tests — DICOM with pixel data."""
    return DATA / "sample_image.dcm"


@pytest.fixture
def sample_dicom_metadata():
    """DICOM with PHI in metadata tags only (no pixel data)."""
    return DATA / "sample_metadata.dcm"


@pytest.fixture
def sample_dicom_image():
    """DICOM CR image with PHI in metadata and 16-bit pixel data."""
    return DATA / "sample_image.dcm"


@pytest.fixture
def sample_dicom_us_overlay():
    """Ultrasound DICOM with PHI burned into pixel data AND in metadata."""
    return DATA / "sample_us_overlay.dcm"


@pytest.fixture
def sample_jpg():
    """JPEG fundus-style image with PHI text burned into the corner."""
    return DATA / "sample_overlay.jpg"


@pytest.fixture
def sample_png():
    """PNG image with PHI text burned into the corner."""
    return DATA / "sample_overlay.png"


@pytest.fixture
def sample_nifti():
    """NIfTI volume with PHI in descrip / aux_file / db_name header fields."""
    return DATA / "sample.nii.gz"


@pytest.fixture
def sample_pdf():
    """PDF report with patient name, DOB, MRN in plain text."""
    return DATA / "sample.pdf"


@pytest.fixture
def sample_tiff():
    """TIFF image with PHI text burned into the corner."""
    return DATA / "sample_exif.tiff"


@pytest.fixture
def temp_output(tmp_path):
    """Temporary output directory cleaned up after each test."""
    return tmp_path / "output"
