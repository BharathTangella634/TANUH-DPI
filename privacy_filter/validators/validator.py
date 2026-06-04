"""
validator.py

Validation engine for MedDeID.

Post-redaction verification.

Pipeline:

    redacted artifact
            ↓
    metadata detection
            ↓
    OCR detection
            ↓
    PHI classification
            ↓
    residual PHI analysis
"""

from __future__ import annotations

import logging

from ..detectors.metadata_detector import MetadataDetector
from ..detectors.ocr_detector import OCRDetector
from ..detectors.phi_detector import PHIDetector

from ..schemas.core import (
    MedicalArtifact,
    PHIEntity,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class Validator:
    """
    Universal validation engine.
    """

    def __init__(
        self,
        ocr_backend: str = "tesseract",
        confidence_threshold: float = 0.50,
    ):

        self.metadata_detector = MetadataDetector()
        self.ocr_detector      = OCRDetector(backend=ocr_backend)
        self.phi_detector      = PHIDetector(confidence_threshold=confidence_threshold)

    def validate(
        self,
        artifact: MedicalArtifact,
    ) -> ValidationResult:
        """
        Validate redacted artifact.
        """

        residual = []

        # Metadata residual — DICOM tags / EXIF / NIfTI header fields
        metadata_hits = self.metadata_detector.detect(artifact)
        residual.extend(metadata_hits)

        # OCR-based residual — reads the actual text content and classifies it
        # as PHI (NAME / DATE / IDENTIFIER …).  TextRegionDetector is NOT used
        # here: after masking, bright image features (exudates, vessels, optic
        # disc) can look like text blobs but are clinical tissue, not PHI.
        # OCR requires reading character glyphs, so it will not mistake
        # tissue for patient text.
        ocr_hits = self.ocr_detector.detect(artifact)
        phi_hits = self.phi_detector.detect(ocr_hits)
        residual.extend(phi_hits)

        risk_score = self._risk_score(
            residual
        )

        passed = len(
            residual
        ) == 0

        return ValidationResult(

            passed=passed,

            risk_score=risk_score,

            residual_phi=residual,

            validator_name=
            "MedDeIDValidator",

            notes=self._summary(
                residual
            ),
        )

    def _risk_score(
        self,
        residual: list[PHIEntity],
    ) -> float:
        """
        Compute residual risk.

        Scale:

            0 → safe

            100 → severe leak
        """

        if not residual:

            return 0.0

        weights = {

            "PERSON_NAME": 25,

            "PATIENT": 25,

            "DOB": 20,

            "DATE": 10,

            "IDENTIFIER": 20,

            "UID": 15,

            "HOSPITAL": 10,

            "AGE": 5,
        }

        score = 0.0

        for entity in residual:

            score += weights.get(

                entity.label,

                5,
            )

        return min(
            score,
            100.0,
        )

    def _summary(
        self,
        residual: list[PHIEntity],
    ) -> str:

        if not residual:

            return (
                "Validation passed."
            )

        labels = sorted({

            e.label

            for e in residual
        })

        return (

            f"Residual PHI detected: "
            f"{', '.join(labels)}"
        )