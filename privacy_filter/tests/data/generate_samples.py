"""
generate_samples.py

Creates synthetic sample files with realistic PHI for each supported format.
Run once to populate tests/data/ before running pytest.

    python3 tests/data/generate_samples.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

OUT = Path(__file__).parent


# ── helpers ───────────────────────────────────────────────────────────────────

def _phi_text_on_image(w: int, h: int, lines: list[str], *, dark_bg: bool = True):
    """Return an RGBA PIL image with PHI text burned into a corner."""
    from PIL import Image, ImageDraw, ImageFont

    mode = "RGB"
    bg   = (0, 0, 0) if dark_bg else (240, 240, 240)
    fg   = (255, 255, 255) if dark_bg else (0, 0, 0)

    img  = Image.new(mode, (w, h), color=bg)
    draw = ImageDraw.Draw(img)

    # Try to use a monospace font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    y = 10
    for line in lines:
        draw.text((10, y), line, fill=fg, font=font)
        y += 22

    return img


# ── DICOM with metadata PHI (no pixel data) ──────────────────────────────────

def make_dicom_metadata(path: Path):
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian

    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)

    ds.SOPClassUID    = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyDate      = "20240101"
    ds.Modality       = "CT"

    # PHI
    ds.PatientName            = "DOE^JOHN"
    ds.PatientID              = "MRN12345"
    ds.IssuerOfPatientID      = "HOSPITAL001"
    ds.PatientBirthDate       = "19800515"
    ds.PatientSex             = "M"
    ds.PatientAge             = "044Y"
    ds.InstitutionName        = "General Hospital"
    ds.ReferringPhysicianName = "SMITH^ALICE"
    ds.AccessionNumber        = "ACC20240001"
    ds.StudyID                = "ST001"

    ds.save_as(str(path), write_like_original=False)
    print(f"  created {path.name}")


# ── DICOM with pixel data (mammography-style CR) ──────────────────────────────

def make_dicom_image(path: Path):
    import numpy as np
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian

    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.1"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)

    rows, cols = 256, 256
    ds.SOPClassUID            = "1.2.840.10008.5.1.4.1.1.1"
    ds.SOPInstanceUID         = generate_uid()
    ds.StudyDate              = "20240101"
    ds.Modality               = "CR"
    ds.Rows                   = rows
    ds.Columns                = cols
    ds.BitsAllocated          = 16
    ds.BitsStored             = 16
    ds.HighBit                = 15
    ds.PixelRepresentation    = 0
    ds.SamplesPerPixel        = 1
    ds.PhotometricInterpretation = "MONOCHROME2"

    # PHI
    ds.PatientName    = "SMITH^JANE"
    ds.PatientID      = "P98765"
    ds.PatientSex     = "F"
    ds.PatientBirthDate = "19750320"
    ds.InstitutionName = "City Radiology"
    ds.AccessionNumber = "ACC20240002"

    # Synthetic X-ray-like pixel data (16-bit gradient)
    arr = np.tile(np.linspace(0, 1023, cols, dtype=np.uint16), (rows, 1))
    ds.PixelData = arr.tobytes()

    ds.save_as(str(path), write_like_original=False)
    print(f"  created {path.name}")


# ── JPG with burned-in text overlay ───────────────────────────────────────────

def make_jpg_overlay(path: Path):
    # Use 2000x1500 so text fits well within the 10% corner scan (200px wide).
    # Each text line is kept short enough to fit in ~200px at 16px monospace.
    lines = [
        "KUMAR,RAJESH",
        "15-06-1978",
        "12-03-2024",
        "OD",
    ]
    img = _phi_text_on_image(2000, 1500, lines, dark_bg=True)
    img.save(str(path), quality=95)
    print(f"  created {path.name}")


# ── PNG with burned-in text overlay ───────────────────────────────────────────

def make_png_overlay(path: Path):
    lines = [
        "GUPTA,PRIYA",
        "01-01-1990",
        "22-05-2024",
        "OS",
    ]
    img = _phi_text_on_image(2000, 1500, lines, dark_bg=True)
    img.save(str(path))
    print(f"  created {path.name}")


# ── OCT / ultrasound-style DICOM with burned-in overlay ──────────────────────

def make_dicom_us_overlay(path: Path):
    """Ultrasound DICOM with patient text burned into the pixel data."""
    import numpy as np
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian
    from PIL import Image
    import io

    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID    = "1.2.840.10008.5.1.4.1.1.3.1"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID          = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)

    lines = ["VERMA,ANIL 02-02-1965", "23-04-2024"]
    pil_img = _phi_text_on_image(512, 512, lines, dark_bg=True)
    arr = np.array(pil_img.convert("L"), dtype=np.uint8)

    rows, cols = arr.shape
    ds.SOPClassUID               = "1.2.840.10008.5.1.4.1.1.3.1"
    ds.SOPInstanceUID            = generate_uid()
    ds.StudyDate                 = "20240423"
    ds.Modality                  = "US"
    ds.Rows                      = rows
    ds.Columns                   = cols
    ds.BitsAllocated             = 8
    ds.BitsStored                = 8
    ds.HighBit                   = 7
    ds.PixelRepresentation       = 0
    ds.SamplesPerPixel           = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BurnedInAnnotation        = "YES"

    # PHI in metadata too
    ds.PatientName     = "VERMA^ANIL"
    ds.PatientID       = "US00987"
    ds.PatientBirthDate = "19650202"
    ds.PatientSex      = "M"
    ds.InstitutionName = "Ultrasound Centre"

    ds.PixelData = arr.tobytes()
    ds.save_as(str(path), write_like_original=False)
    print(f"  created {path.name}")


# ── NIfTI with PHI in header ──────────────────────────────────────────────────

def make_nifti(path: Path):
    try:
        import nibabel as nib
        import numpy as np
    except ImportError:
        print(f"  SKIP {path.name} — nibabel not installed")
        return

    arr = np.zeros((64, 64, 10), dtype=np.float32)
    img = nib.Nifti1Image(arr, np.eye(4))

    # Inject PHI into header free-text fields
    hdr = img.header
    hdr["descrip"] = b"Patient: NAIR SURESH DOB 1982-07-20 MRN 556677"
    hdr["aux_file"] = b"suresh_nair_19820720"
    hdr["db_name"]  = b"NAIR^SURESH"

    nib.save(img, str(path))
    print(f"  created {path.name}")


# ── PDF with patient text ─────────────────────────────────────────────────────

def make_pdf(path: Path):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  SKIP {path.name} — PyMuPDF not installed")
        return

    doc  = fitz.open()
    page = doc.new_page(width=595, height=842)
    phi  = (
        "Patient Report\n\n"
        "Name   : MEHTA, ROHIT\n"
        "DOB    : 03-09-1971\n"
        "MRN    : 7890123\n"
        "Gender : Male\n"
        "Date   : 10-01-2024\n"
    )
    page.insert_text((50, 100), phi, fontsize=12)
    doc.save(str(path))
    doc.close()
    print(f"  created {path.name}")


# ── TIFF with EXIF PHI ────────────────────────────────────────────────────────

def make_tiff_exif(path: Path):
    """TIFF with burned-in text overlay at 2000x1500 to match corner scan assumptions."""
    from PIL import Image

    lines = ["PATEL,MEENA", "14-04-1988", "05-02-2024", "OS"]
    img   = _phi_text_on_image(2000, 1500, lines, dark_bg=True)
    img.save(str(path))
    print(f"  created {path.name}")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Generating test samples in {OUT}/")

    make_dicom_metadata(OUT / "sample_metadata.dcm")
    make_dicom_image(OUT / "sample_image.dcm")
    make_dicom_us_overlay(OUT / "sample_us_overlay.dcm")
    make_jpg_overlay(OUT / "sample_overlay.jpg")
    make_png_overlay(OUT / "sample_overlay.png")
    make_nifti(OUT / "sample.nii.gz")
    make_pdf(OUT / "sample.pdf")
    make_tiff_exif(OUT / "sample_exif.tiff")

    print("\nDone. Run: pytest tests/ -v")
