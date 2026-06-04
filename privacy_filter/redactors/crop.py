"""
crop.py

Crop-based PHI redactor for MedDeID.

Supports:

    overlay band removal
    header/footer stripping
    side-panel removal

Useful for:

    ultrasound
    OCT
    MRI screenshots
    PDFs
"""

from __future__ import annotations

import logging

import numpy as np

from ..schemas.core import (
    BoundingBox,
    MedicalArtifact,
    PHIEntity,
    RedactionMethod,
    RedactionReport,
)

from ..utils.image import (

    normalize_images,

    preprocess_for_ocr,
)

logger = logging.getLogger(__name__)


class CropRedactor:
    """
    Crop-based redactor.

    Removes PHI-heavy border regions.
    """

    def __init__(
        self,
        max_crop_fraction: float = 0.35,
    ):

        self.max_crop_fraction = (
            max_crop_fraction
        )

    def redact(
        self,
        artifact: MedicalArtifact,
        entities: list[PHIEntity],
    ) -> tuple[
        MedicalArtifact,
        RedactionReport,
    ]:

        report = RedactionReport()

        if artifact.image is None:

            return artifact, report

        images = normalize_images(
            artifact.image
        )

        output = []

        for img in images:

            redacted = self._crop_image(

                img,

                entities,
            )

            output.append(
                redacted
            )

        artifact.image = (

            output[0]

            if len(output) == 1

            else output
        )

        report.burnedin_removed = len(
            entities
        )

        report.detected_phi.extend(
            entities
        )

        report.redaction_methods.append(

            RedactionMethod.CROP
        )

        return artifact, report

    

    def _crop_image(
        self,
        image: np.ndarray,
        entities: list[PHIEntity],
    ) -> np.ndarray:
        """
        Infer crop bands from PHI boxes.
        """

        h, w = image.shape[:2]

        top_crop = 0
        bottom_crop = h

        left_crop = 0
        right_crop = w

        max_h_crop = int(
            h * self.max_crop_fraction
        )

        max_w_crop = int(
            w * self.max_crop_fraction
        )

        for entity in entities:

            if entity.bbox is None:

                continue

            bbox = entity.bbox

            # ---------- TOP BAND ----------

            if bbox.y2 < max_h_crop:

                top_crop = max(
                    top_crop,
                    bbox.y2,
                )

            # ---------- BOTTOM BAND ----------

            if bbox.y1 > h-max_h_crop:

                bottom_crop = min(
                    bottom_crop,
                    bbox.y1,
                )

            # ---------- LEFT PANEL ----------

            if bbox.x2 < max_w_crop:

                left_crop = max(
                    left_crop,
                    bbox.x2,
                )

            # ---------- RIGHT PANEL ----------

            if bbox.x1 > w-max_w_crop:

                right_crop = min(
                    right_crop,
                    bbox.x1,
                )

        # safety

        if top_crop >= bottom_crop:

            logger.warning(
                "Invalid vertical crop."
            )

            return image

        if left_crop >= right_crop:

            logger.warning(
                "Invalid horizontal crop."
            )

            return image

        cropped = image[
            top_crop:bottom_crop,
            left_crop:right_crop,
        ]

        return cropped