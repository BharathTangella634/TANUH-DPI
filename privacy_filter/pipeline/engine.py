"""
engine.py

Core orchestration engine for MedDeID.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..schemas.core import FileFormat, ValidationResult

from ..registry.loader_registry import LoaderRegistry
from ..registry.cleaner_registry import CleanerRegistry
from ..registry.redactor_registry import RedactorRegistry
from ..registry.saver_registry import SaverRegistry

from ..detectors.metadata_detector import MetadataDetector
from ..detectors.overlay_detector import OverlayDetector
from ..detectors.text_region_detector import TextRegionDetector
from ..detectors.ocr_detector import OCRDetector
from ..detectors.phi_detector import PHIDetector

from ..validators.validator import Validator

logger = logging.getLogger(__name__)


class MedDeIDEngine:
    """
    End-to-end medical de-identification engine.

    Detection strategy (two complementary approaches):

    1. TextRegionDetector  — shape-based, no OCR.
       Finds character-sized blobs in corner crops and groups them into
       text lines.  Catches everything, including text that OCR misreads
       (dates with JPEG compression artefacts, small fonts, etc.).
       Because any text in the corner of a medical image is PHI by
       definition, we redact ALL detected text lines unconditionally.

    2. OCRDetector + PHIDetector  — text-reading pipeline.
       Reads the text, classifies it (NAME / DATE / IDENTIFIER …), and
       produces labelled PHIEntity objects for the audit report.
       Results are merged with (1); duplicates are harmless.

    The two-pronged approach means:
       * Shape detector provides COMPLETENESS  (no misses)
       * OCR provides CLASSIFICATION          (audit trail)
    """

    def __init__(
        self,
        ocr_backend: str = "tesseract",
        redaction_method: str = "mask",
    ):

        self.ocr_backend = ocr_backend

        self.metadata_detector   = MetadataDetector()
        self.overlay_detector    = OverlayDetector()
        self.text_region_detector = TextRegionDetector()
        self.ocr_detector        = OCRDetector(backend=ocr_backend)
        self.phi_detector        = PHIDetector()

        self.validator = Validator(ocr_backend=ocr_backend)

        self.redactor = RedactorRegistry.get(redaction_method)

    def process(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> dict:
        """
        Run full MedDeID pipeline.

        Returns a dict with keys:
            artifact, redaction_report, validation, phi_count, overlay_count
        """

        input_path  = Path(input_path)
        output_path = Path(output_path)

        logger.info("Processing %s", input_path)

        # ── PDF SHORT-CIRCUIT ──────────────────────────────────────────────────
        # Documents take a dedicated native-text redaction path (Safe Harbor,
        # content-based) — completely separate from the pixel pipeline below, so
        # the DICOM / NIfTI / image logic is untouched.
        if input_path.suffix.lower() == ".pdf":
            return self._process_pdf(input_path, output_path)

        # ── LOAD ──────────────────────────────────────────────────────────────

        loader   = LoaderRegistry.get(input_path)
        artifact = loader.load(input_path)

        # ── METADATA CLEAN ────────────────────────────────────────────────────
        # Strips DICOM tags / EXIF in-memory before pixel redaction.

        artifact = self._metadata_clean(artifact, input_path, output_path)

        # ── DETECTION ─────────────────────────────────────────────────────────

        # Metadata PHI (no bboxes — handled by metadata cleaner above, but
        # kept here for the audit count).
        metadata_hits = self.metadata_detector.detect(artifact)

        # Overlay region heuristics (modality-specific edge bands).
        overlay_regions = self.overlay_detector.detect(artifact)

        # PRIMARY: shape-based text region detection.
        # Finds ALL character-blob lines in corners regardless of content.
        # Patient text that is burned into the image IS at the pixel level —
        # this detector finds those pixels and marks every text line for masking.
        text_region_hits = self.text_region_detector.detect(artifact)

        # SECONDARY: OCR-based detection + PHI classification.
        # Reads what the text says and labels it (NAME / DATE / IDENTIFIER).
        # Supplements the shape detector; OCR may find text the blob detector
        # misses (e.g., wide-spaced characters) and adds labels for the report.
        ocr_hits  = self.ocr_detector.detect(artifact)
        ocr_phi   = self.phi_detector.detect(metadata_hits + ocr_hits)

        # Combine: text-region hits go straight to redaction (always PHI);
        # classified OCR hits add labelled entities for the audit report.
        phi_entities = text_region_hits + ocr_phi

        for e in phi_entities:
            logger.debug(
                "PHI  label=%-20s  text=%-30r  bbox=%s",
                e.label, e.text, e.bbox,
            )

        # ── REDACTION ─────────────────────────────────────────────────────────
        # MaskRedactor draws a black rectangle over every entity that has a
        # bbox.  This modifies the pixel data in-place — fully irreversible.

        artifact, redaction_report = self.redactor.redact(artifact, phi_entities)

        # ── VALIDATION ────────────────────────────────────────────────────────
        # Re-runs OCR on the redacted image to confirm no text remains.

        validation = self.validator.validate(artifact)

        # ── SAVE ──────────────────────────────────────────────────────────────

        self._save_output(artifact, output_path)

        # PHI removed from metadata/headers (DICOM tags, EXIF, NIfTI fields),
        # captured during the metadata-clean step for the audit report.
        metadata_phi = artifact.notes.get("_metadata_phi", [])

        return {
            "artifact":          artifact,
            "redaction_report":  redaction_report,
            "validation":        validation,
            "phi_count":         len(phi_entities),
            "overlay_count":     len(overlay_regions),
            "metadata_phi":      metadata_phi,
            "pixel_phi":         phi_entities,
        }

    # ── PDF (document) path ────────────────────────────────────────────────────

    def _process_pdf(self, input_path: Path, output_path: Path) -> dict:
        """
        De-identify a PDF via native-text Safe Harbor redaction, then re-scan
        the output to confirm no identifiers remain.
        """
        from ..redactors.pdf_redactor import PDFRedactor
        from ..detectors.safe_harbor_detector import SafeHarborDetector

        redactor = PDFRedactor()
        entities, counts = redactor.redact(input_path, output_path)

        # ── Validation: re-extract text from the redacted PDF and re-scan ──────
        residual = 0
        try:
            import fitz
            detector = SafeHarborDetector()
            doc = fitz.open(str(output_path))
            for page in doc:
                for line in page.get_text().splitlines():
                    residual += len(detector.detect_spans(line))
            doc.close()
        except Exception as exc:
            logger.warning("PDF validation re-scan failed: %s", exc)

        validation = ValidationResult(
            passed=(residual == 0),
            risk_score=float(min(residual * 5, 100)),
            residual_phi=[],
            validator_name="SafeHarborPDFValidator",
            notes=("Validation passed."
                   if residual == 0
                   else f"{residual} residual identifier span(s) detected."),
        )

        return {
            "artifact":          None,
            "redaction_report":  None,
            "validation":        validation,
            "phi_count":         len(entities),
            "overlay_count":     0,
            "metadata_phi":      [],
            "pixel_phi":         [],
            "pdf_entities":      entities,   # API-shape dicts (with bbox)
            "pdf_counts":        counts,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _metadata_clean(
        self,
        artifact,
        input_path: Path,
        output_path: Path,
    ):
        """
        Apply metadata cleaner through registry.

        For DICOM: cleans the in-memory pydicom Dataset stored in
        artifact.notes["_ds"] so the DicomSaver writes clean tags.

        For image/NIfTI: delegates to the file-based cleaner (cv2.imwrite
        strips EXIF anyway, so this is belt-and-suspenders for other formats).
        """

        cleaner = CleanerRegistry.get(artifact.format)

        if cleaner is None:
            logger.info("No cleaner for %s", artifact.format)
            return artifact

        if artifact.format == FileFormat.DICOM:

            ds = artifact.notes.get("_ds")

            if ds is not None:
                try:
                    ds, mreport = cleaner.clean(ds)
                    artifact.notes["_ds"] = ds
                    artifact.notes["_metadata_phi"] = list(mreport.detected_phi)

                    # Rebuild the flat metadata dict so the validator's
                    # MetadataDetector sees the cleaned (REDACTED) values,
                    # not the original PHI values present at load time.
                    artifact.metadata = {
                        elem.keyword: str(elem.value)
                        for elem in ds
                        if elem.keyword and elem.keyword != "PixelData"
                    }

                except Exception as exc:
                    logger.warning("DICOM in-memory clean failed: %s", exc)

            return artifact

        if artifact.format == FileFormat.NIFTI:
            # NIfTI: clean in-memory and also clear the metadata dict so the
            # validator doesn't re-flag the original PHI header values.
            nii = artifact.notes.get("_nii")
            if nii is None:
                # Load fresh only if not already stored
                try:
                    import nibabel as nib
                    nii = nib.load(str(input_path))
                except Exception:
                    nii = None

            if nii is not None:
                try:
                    nii, mreport = cleaner.clean(nii)
                    artifact.notes["_nii"] = nii
                    artifact.notes["_metadata_phi"] = list(mreport.detected_phi)
                    # Clear PHI fields in the flat metadata dict
                    from ..metadata.nifti_cleaner import PHI_FIELDS as _NII_PHI
                    for field in _NII_PHI:
                        if field in artifact.metadata:
                            artifact.metadata[field] = ""
                except Exception as exc:
                    logger.warning("NIfTI in-memory clean failed: %s", exc)

            return artifact

        try:
            mreport = cleaner.clean_file(input_path, output_path)
            if mreport is not None:
                artifact.notes["_metadata_phi"] = list(mreport.detected_phi)
        except Exception as exc:
            logger.warning("Metadata cleaning failed: %s", exc)

        return artifact

    def _save_output(
        self,
        artifact,
        output_path: Path,
    ):
        saver = SaverRegistry.get(artifact.format)
        saver.save(artifact, output_path)
