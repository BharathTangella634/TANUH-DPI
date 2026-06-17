"""
inpaint.py

Inpainting-based PHI redactor for MedDeID.

Uses OpenCV inpainting to remove:

    OCR regions
    overlays
    burned-in annotations

while preserving surrounding image appearance.

Supports:

    grayscale
    RGB
    uint16 medical images
    multi-frame datasets
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


class InpaintRedactor:
    """
    Appearance-preserving redactor.
    """

    def __init__(
        self,
        radius: int = 5,
        pad_pixels: int = 4,
        algorithm: str = "telea",
    ):

        self.radius = radius

        self.pad = pad_pixels

        algo = algorithm.lower()

        if algo == "telea":

            self.algorithm = cv2.INPAINT_TELEA

        elif algo == "ns":

            self.algorithm = cv2.INPAINT_NS

        else:

            raise ValueError(
                f"Unsupported algorithm: "
                f"{algorithm}"
            )

    def redact(
        self,
        artifact: MedicalArtifact,
        entities: list[PHIEntity],
    ) -> tuple[
        MedicalArtifact,
        RedactionReport,
    ]:
        """
        Apply inpainting redaction.
        """

        report = RedactionReport()

        if artifact.image is None:

            return artifact, report

        images = normalize_images(
            artifact.image
        )

        output = []

        for img in images:

            redacted = self._inpaint_image(

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

            RedactionMethod.INPAINT
        )

        return artifact, report

    # def _normalize_images(
    #     self,
    #     image,
    # ) -> list[np.ndarray]:

    #     if isinstance(
    #         image,
    #         list,
    #     ):

    #         return image

    #     if isinstance(
    #         image,
    #         np.ndarray,
    #     ):

    #         if image.ndim == 4:

    #             return [

    #                 frame

    #                 for frame in image
    #             ]

    #         return [image]

    #     return []

    def _inpaint_image(
        self,
        image: np.ndarray,
        entities: list[PHIEntity],
    ) -> np.ndarray:
        """
        Inpaint PHI regions.
        """

        original_dtype = image.dtype

        working = image.copy()

        if working.dtype != np.uint8:

            working = cv2.normalize(

                working,

                None,

                0,

                255,

                cv2.NORM_MINMAX,
            )

            working = working.astype(
                np.uint8
            )

        mask = self._build_mask(

            working.shape[:2],

            entities,
        )

        if np.count_nonzero(mask) == 0:

            return image

        try:

            inpainted = cv2.inpaint(

                working,

                mask,

                self.radius,

                self.algorithm,
            )

        except Exception as exc:

            logger.warning(

                "Inpainting failed: %s",

                exc,
            )

            return image

        # restore dtype when possible

        if original_dtype != np.uint8:

            inpainted = inpainted.astype(
                original_dtype
            )

        return inpainted

    def _build_mask(
        self,
        shape: tuple[int,int],
        entities: list[PHIEntity],
    ) -> np.ndarray:
        """
        Build binary inpainting mask.
        """

        h, w = shape

        mask = np.zeros(

            (h,w),

            dtype=np.uint8,
        )

        for entity in entities:

            if entity.bbox is None:

                continue

            bbox = entity.bbox

            x1 = max(
                0,
                bbox.x1-self.pad,
            )

            y1 = max(
                0,
                bbox.y1-self.pad,
            )

            x2 = min(
                w,
                bbox.x2+self.pad,
            )

            y2 = min(
                h,
                bbox.y2+self.pad,
            )

            cv2.rectangle(

                mask,

                (x1,y1),

                (x2,y2),

                color=255,

                thickness=-1,
            )

        return mask