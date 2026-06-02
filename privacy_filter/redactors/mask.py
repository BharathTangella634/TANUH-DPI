"""
mask.py

Mask-based PHI redactor for MedDeID.

Applies:

    black-box masking

to:

    OCR detections
    overlay detections
    metadata-driven regions

Supports:

    2D images
    RGB
    grayscale
    multi-frame data
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from ..schemas.core import (
    BoundingBox,
    MedicalArtifact,
    PHIEntity,
    RedactionMethod,
    RedactionReport,
)
from ..utils.image import (
    normalize_images)
logger = logging.getLogger(__name__)


class MaskRedactor:
    """
    Black-mask redactor.
    """

    def __init__(
        self,
        pad_pixels: int = 3,
    ):

        self.pad = pad_pixels

    def redact(
        self,
        artifact: MedicalArtifact,
        entities: list[PHIEntity],
    ) -> tuple[
        MedicalArtifact,
        RedactionReport,
    ]:
        """
        Apply masking.
        """

        report = RedactionReport()

        if artifact.image is None:

            return artifact, report

        images = normalize_images(
            artifact.image
        )

        output = []

        for img in images:

            redacted = img.copy()

            for entity in entities:

                if entity.bbox is None:

                    continue

                redacted = self._mask_region(

                    redacted,

                    entity.bbox,
                )

                report.burnedin_removed += 1

            output.append(
                redacted
            )

        artifact.image = (
            output[0]

            if len(output) == 1

            else output
        )

        report.redaction_methods.append(

            RedactionMethod.MASK
        )

        report.detected_phi.extend(
            entities
        )

        return artifact, report


    def _mask_region(
        self,
        image: np.ndarray,
        bbox: BoundingBox,
    ) -> np.ndarray:
        """
        Apply black rectangle.
        """

        h, w = image.shape[:2]

        x1 = max(
            0,
            bbox.x1 - self.pad,
        )

        y1 = max(
            0,
            bbox.y1 - self.pad,
        )

        x2 = min(
            w,
            bbox.x2 + self.pad,
        )

        y2 = min(
            h,
            bbox.y2 + self.pad,
        )

        cv2.rectangle(

            image,

            (x1,y1),

            (x2,y2),

            color=0,

            thickness=-1,
        )

        return image