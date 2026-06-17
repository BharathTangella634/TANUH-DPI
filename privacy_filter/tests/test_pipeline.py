"""
test_pipeline.py

End-to-end pipeline tests for MedDeID covering every supported format.

Each test verifies:
    1. Pipeline completes without exception
    2. Output file is written to disk
    3. Validation passes (risk score == 0)
    4. PHI is NOT present in the output (format-specific checks)
    5. Clinical content is NOT destroyed (image shape / pixel range preserved)
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

import privacy_filter.registry  # bootstrap all loaders / savers / cleaners
from privacy_filter.pipeline.engine import MedDeIDEngine


# ── helpers ───────────────────────────────────────────────────────────────────

PHI_STRINGS = [
    "DOE", "JOHN", "SMITH", "JANE", "KUMAR", "RAJESH",
    "GUPTA", "PRIYA", "VERMA", "ANIL", "NAIR", "SURESH",
    "PATEL", "MEENA", "MEHTA", "ROHIT",
    "MRN12345", "P98765", "US00987",
    "General Hospital", "City Radiology", "Ultrasound Centre",
]


def _engine(redactor: str = "mask") -> MedDeIDEngine:
    return MedDeIDEngine(ocr_backend="tesseract", redaction_method=redactor)


def _phi_free(text: str) -> bool:
    upper = text.upper()
    return not any(s.upper() in upper for s in PHI_STRINGS)


# ── DICOM metadata-only ───────────────────────────────────────────────────────

class TestDicomMetadata:

    def test_completes_and_writes_output(self, sample_dicom_metadata, tmp_path):
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_metadata, out)
        assert out.exists()

    def test_validation_passes(self, sample_dicom_metadata, tmp_path):
        out = tmp_path / "out.dcm"
        result = _engine().process(sample_dicom_metadata, out)
        assert result["validation"].passed
        assert result["validation"].risk_score == 0.0

    def test_phi_tags_redacted(self, sample_dicom_metadata, tmp_path):
        import pydicom
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_metadata, out)
        ds = pydicom.dcmread(str(out), force=True)
        for tag in ["PatientName", "PatientID", "PatientBirthDate",
                    "InstitutionName", "AccessionNumber", "ReferringPhysicianName"]:
            val = str(getattr(ds, tag, "")).strip()
            assert _phi_free(val), f"{tag} still contains PHI: {val!r}"

    def test_deidentified_flag_set(self, sample_dicom_metadata, tmp_path):
        import pydicom
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_metadata, out)
        ds = pydicom.dcmread(str(out), force=True)
        assert getattr(ds, "PatientIdentityRemoved", "") == "YES"

    def test_study_date_normalized(self, sample_dicom_metadata, tmp_path):
        import pydicom
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_metadata, out)
        ds = pydicom.dcmread(str(out), force=True)
        assert getattr(ds, "StudyDate", "") == "19000101"


# ── DICOM with pixel data (CR) ────────────────────────────────────────────────

class TestDicomImage:

    def test_completes(self, sample_dicom_image, tmp_path):
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_image, out)
        assert out.exists()

    def test_validation_passes(self, sample_dicom_image, tmp_path):
        out = tmp_path / "out.dcm"
        result = _engine().process(sample_dicom_image, out)
        assert result["validation"].passed

    def test_phi_tags_redacted(self, sample_dicom_image, tmp_path):
        import pydicom
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_image, out)
        ds = pydicom.dcmread(str(out), force=True)
        for tag in ["PatientName", "PatientID", "InstitutionName"]:
            val = str(getattr(ds, tag, "")).strip()
            assert _phi_free(val), f"{tag} PHI: {val!r}"

    def test_pixel_data_preserved(self, sample_dicom_image, tmp_path):
        import pydicom
        orig = pydicom.dcmread(str(sample_dicom_image), force=True)
        out  = tmp_path / "out.dcm"
        _engine().process(sample_dicom_image, out)
        ds = pydicom.dcmread(str(out), force=True)
        assert "PixelData" in ds
        assert ds.Rows == orig.Rows
        assert ds.Columns == orig.Columns


# ── Ultrasound DICOM with burned-in overlay ───────────────────────────────────

class TestDicomUltrasoundOverlay:

    def test_completes_and_validates(self, sample_dicom_us_overlay, tmp_path):
        out = tmp_path / "out.dcm"
        result = _engine().process(sample_dicom_us_overlay, out)
        assert out.exists()
        assert result["validation"].passed
        assert result["validation"].risk_score == 0.0

    def test_phi_tags_redacted(self, sample_dicom_us_overlay, tmp_path):
        import pydicom
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_us_overlay, out)
        ds = pydicom.dcmread(str(out), force=True)
        for tag in ["PatientName", "PatientID", "InstitutionName"]:
            val = str(getattr(ds, tag, "")).strip()
            assert _phi_free(val), f"{tag} PHI: {val!r}"

    def test_pixel_data_preserved(self, sample_dicom_us_overlay, tmp_path):
        import pydicom
        orig = pydicom.dcmread(str(sample_dicom_us_overlay), force=True)
        out  = tmp_path / "out.dcm"
        _engine().process(sample_dicom_us_overlay, out)
        ds = pydicom.dcmread(str(out), force=True)
        assert "PixelData" in ds
        assert ds.Rows == orig.Rows and ds.Columns == orig.Columns

    def test_overlay_text_blacked_out(self, sample_dicom_us_overlay, tmp_path):
        """Bright text pixels in the TL corner must be substantially reduced."""
        import pydicom
        orig_arr = pydicom.dcmread(str(sample_dicom_us_overlay), force=True).pixel_array
        out = tmp_path / "out.dcm"
        _engine().process(sample_dicom_us_overlay, out)
        out_arr = pydicom.dcmread(str(out), force=True).pixel_array
        h, w   = orig_arr.shape[:2]
        ch, cw = int(h * 0.12), int(w * 0.12)
        before = (orig_arr[0:ch, 0:cw] > 200).sum()
        after  = (out_arr[0:ch,  0:cw] > 200).sum()
        assert after <= before * 0.10, f"Overlay not removed: {before} → {after} bright px"


# ── JPEG with burned-in PHI ───────────────────────────────────────────────────

class TestJpegOverlay:

    def test_completes_and_validates(self, sample_jpg, tmp_path):
        out = tmp_path / "out.jpg"
        result = _engine().process(sample_jpg, out)
        assert out.exists()
        assert result["validation"].passed

    def test_bright_pixels_removed(self, sample_jpg, tmp_path):
        import cv2
        orig = cv2.cvtColor(cv2.imread(str(sample_jpg)), cv2.COLOR_BGR2GRAY)
        out  = tmp_path / "out.jpg"
        _engine().process(sample_jpg, out)
        red  = cv2.cvtColor(cv2.imread(str(out)), cv2.COLOR_BGR2GRAY)
        h, w = orig.shape
        ch, cw = int(h * 0.15), int(w * 0.15)
        before = (orig[0:ch, 0:cw] > 200).sum()
        after  = (red[0:ch,  0:cw] > 200).sum()
        assert after < before * 0.10, f"{before} → {after} bright px in TL corner"

    def test_image_body_unchanged(self, sample_jpg, tmp_path):
        """Centre of image (far from corners) must not be altered."""
        import cv2
        import numpy as np
        orig = cv2.imread(str(sample_jpg)).astype(np.int32)
        out  = tmp_path / "out.jpg"
        _engine().process(sample_jpg, out)
        red  = cv2.imread(str(out)).astype(np.int32)
        h, w = orig.shape[:2]
        c_orig = orig[h//4:3*h//4, w//4:3*w//4]
        c_red  = red[h//4:3*h//4,  w//4:3*w//4]
        assert np.abs(c_orig - c_red).mean() < 5.0


# ── PNG with burned-in PHI ────────────────────────────────────────────────────

class TestPngOverlay:

    def test_completes_and_validates(self, sample_png, tmp_path):
        out = tmp_path / "out.png"
        result = _engine().process(sample_png, out)
        assert out.exists()
        assert result["validation"].passed

    def test_bright_pixels_removed(self, sample_png, tmp_path):
        import cv2
        orig = cv2.cvtColor(cv2.imread(str(sample_png)), cv2.COLOR_BGR2GRAY)
        out  = tmp_path / "out.png"
        _engine().process(sample_png, out)
        red  = cv2.cvtColor(cv2.imread(str(out)), cv2.COLOR_BGR2GRAY)
        h, w = orig.shape
        ch, cw = int(h * 0.15), int(w * 0.15)
        assert (red[0:ch, 0:cw] > 200).sum() < (orig[0:ch, 0:cw] > 200).sum() * 0.10


# ── NIfTI ─────────────────────────────────────────────────────────────────────

class TestNifti:

    def test_completes(self, sample_nifti, tmp_path):
        out = tmp_path / "out.nii.gz"
        _engine().process(sample_nifti, out)
        assert out.exists()

    def test_validation_passes(self, sample_nifti, tmp_path):
        out = tmp_path / "out.nii.gz"
        result = _engine().process(sample_nifti, out)
        assert result["validation"].passed

    def test_header_phi_cleared(self, sample_nifti, tmp_path):
        import nibabel as nib
        out = tmp_path / "out.nii.gz"
        _engine().process(sample_nifti, out)
        hdr = nib.load(str(out)).header
        for field in ("descrip", "aux_file", "db_name"):
            val = hdr[field].tobytes().rstrip(b"\x00").decode("latin-1", errors="replace")
            assert _phi_free(val), f"NIfTI {field} still has PHI: {val!r}"

    def test_volume_shape_preserved(self, sample_nifti, tmp_path):
        import nibabel as nib
        orig = nib.load(str(sample_nifti)).get_fdata()
        out  = tmp_path / "out.nii.gz"
        _engine().process(sample_nifti, out)
        assert nib.load(str(out)).get_fdata().shape == orig.shape


# ── PDF ───────────────────────────────────────────────────────────────────────

class TestPdf:

    def test_completes(self, sample_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        _engine().process(sample_pdf, out)
        assert out.exists()

    def test_validation_passes(self, sample_pdf, tmp_path):
        out = tmp_path / "out.pdf"
        result = _engine().process(sample_pdf, out)
        assert result["validation"].passed


# ── TIFF ──────────────────────────────────────────────────────────────────────

class TestTiff:

    def test_completes_and_validates(self, sample_tiff, tmp_path):
        out = tmp_path / "out.tiff"
        result = _engine().process(sample_tiff, out)
        assert out.exists()
        assert result["validation"].passed

    def test_bright_pixels_removed(self, sample_tiff, tmp_path):
        import cv2
        orig = cv2.cvtColor(cv2.imread(str(sample_tiff)), cv2.COLOR_BGR2GRAY)
        out  = tmp_path / "out.tiff"
        _engine().process(sample_tiff, out)
        red  = cv2.cvtColor(cv2.imread(str(out)), cv2.COLOR_BGR2GRAY)
        h, w = orig.shape
        ch, cw = int(h * 0.15), int(w * 0.15)
        assert (red[0:ch, 0:cw] > 200).sum() < (orig[0:ch, 0:cw] > 200).sum() * 0.10


# ── Redactor variants ─────────────────────────────────────────────────────────

class TestRedactors:
    """All three redaction strategies must produce outputs with low risk scores."""

    @pytest.mark.parametrize("redactor", ["mask", "crop", "inpaint"])
    def test_redactor_on_jpg(self, sample_jpg, tmp_path, redactor):
        out = tmp_path / f"out_{redactor}.jpg"
        result = _engine(redactor).process(sample_jpg, out)
        assert out.exists(), f"{redactor} produced no output"
        assert result["validation"].risk_score < 50, (
            f"{redactor} risk={result['validation'].risk_score}"
        )


# ── Safe Harbor PDF redaction (document text path) ────────────────────────────

class TestPdfSafeHarbor:
    """
    Real-world lab/radiology PDFs: every Safe Harbor identifier must be removed
    (patient name, physician names, registration/bill/request numbers, staff
    codes, ages, category, dates, times, IPs/URLs, QR codes, barcodes) while ALL
    clinical content is preserved.
    """

    DATA = Path(__file__).parent

    LAB_PHI = ["RAJA", "SHETTY", "MADHU", "AKILA", "ARPITHA", "PALLAVI",
               "3035530", "4243169", "10072660", "59460", "GENERAL"]
    LAB_CLINICAL = ["PROSTATE", "CREATININE", "SODIUM", "11100", "REFERENCE"]

    REPORT_PHI = ["RAJA", "SHETTY", "AMRUTHRAJ", "GOWDA", "3035530",
                  "1742225", "10330115", "10.10.14.19"]
    REPORT_CLINICAL = ["KIDNEY", "BLADDER", "prostatomegaly",
                       "Prevoid urine", "able to hold urine"]

    def _run(self, name, tmp_path):
        import fitz
        src = self.DATA / name
        if not src.exists():
            pytest.skip(f"{name} not present")
        out = tmp_path / "redacted.pdf"
        result = _engine().process(src, out)
        text = "\n".join(p.get_text() for p in fitz.open(str(out)))
        return result, text

    def test_lab_phi_removed(self, tmp_path):
        result, text = self._run("rajashetty lab.pdf", tmp_path)
        leaked = [p for p in self.LAB_PHI if p.lower() in text.lower()]
        assert leaked == [], f"PHI leaked: {leaked}"
        assert result["validation"].passed

    def test_lab_clinical_preserved(self, tmp_path):
        _result, text = self._run("rajashetty lab.pdf", tmp_path)
        missing = [c for c in self.LAB_CLINICAL if c.lower() not in text.lower()]
        assert missing == [], f"clinical content lost: {missing}"

    def test_report_phi_removed(self, tmp_path):
        result, text = self._run("rajashetty report.pdf", tmp_path)
        leaked = [p for p in self.REPORT_PHI if p.lower() in text.lower()]
        assert leaked == [], f"PHI leaked: {leaked}"
        assert result["validation"].passed

    def test_report_clinical_preserved(self, tmp_path):
        _result, text = self._run("rajashetty report.pdf", tmp_path)
        missing = [c for c in self.REPORT_CLINICAL if c.lower() not in text.lower()]
        assert missing == [], f"clinical content lost: {missing}"
