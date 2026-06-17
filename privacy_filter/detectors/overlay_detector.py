"""
overlay_detector.py

Medical overlay detector for MedDeID.

Detects likely burned-in annotation regions.

Supports:

    MRI
    CT
    OCT
    Ultrasound
    Fundus
    PDFs
    screenshots
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from ..schemas.core import (
    BoundingBox,
    MedicalArtifact,
    Modality,
    OverlayRegion,
)

from ..utils.image import (

    normalize_images,

    to_uint8,

    to_grayscale,
)

logger = logging.getLogger(__name__)


class OverlayDetector:
    """
    Medical overlay detector.

    Strategy:

        1. modality heuristics
        2. corner scan
        3. edge-band scan
        4. high-contrast text-like regions
    """

    def __init__(

        self,

        corner_fraction: float = 0.20,

        edge_fraction: float = 0.10,
    ):

        self.corner_fraction = corner_fraction

        self.edge_fraction = edge_fraction

    def detect(
        self,
        artifact: MedicalArtifact,
    ) -> list[OverlayRegion]:

        if artifact.image is None:

            return []

        images = normalize_images(
            artifact.image
        )

        regions = []

        modality = getattr(
            artifact,
            "modality",
            None,
        )

        for img in images:

            regions.extend(

                self._detect_single(

                    img,

                    modality,
                )
            )

        return regions

    def _detect_single(
        self,
        image: np.ndarray,
        modality: Modality | None,
    ) -> list[OverlayRegion]:

        image = self._prepare(
            image
        )

        h, w = image.shape[:2]

        regions = []

        regions.extend(

            self._corner_regions(
                h,
                w,
            )
        )

        regions.extend(

            self._edge_regions(
                h,
                w,
                modality,
            )
        )

        regions.extend(

            self._contrast_regions(
                image
            )
        )

        return regions

    def _prepare(
        self,
        image: np.ndarray,
    ) -> np.ndarray:

        image = to_uint8(
            image
        )

        image = to_grayscale(
            image
        )

        return image

    def _corner_regions(
        self,
        h: int,
        w: int,
    ) -> list[OverlayRegion]:

        cw = int(
            w * self.corner_fraction
        )

        ch = int(
            h * self.corner_fraction
        )

        boxes = [

            ("TOP_LEFT",0,0,cw,ch),

            ("TOP_RIGHT",w-cw,0,w,ch),

            ("BOTTOM_LEFT",0,h-ch,cw,h),

            ("BOTTOM_RIGHT",w-cw,h-ch,w,h),
        ]

        return [

            OverlayRegion(

                bbox=BoundingBox(

                    x1=x1,
                    y1=y1,

                    x2=x2,
                    y2=y2,
                ),

                confidence=0.80,

                source=name,
            )

            for name,x1,y1,x2,y2
            in boxes
        ]

    def _edge_regions(
        self,
        h: int,
        w: int,
        modality: Modality | None,
    ) -> list[OverlayRegion]:

        edge = int(
            h * self.edge_fraction
        )

        regions = []

        if modality in {

            Modality.ULTRASOUND,

            Modality.OCT,
        }:

            regions.append(

                OverlayRegion(

                    bbox=BoundingBox(

                        x1=0,
                        y1=0,

                        x2=w,
                        y2=edge,
                    ),

                    confidence=0.95,

                    source="TOP_BAND",
                )
            )

        if modality in {

            Modality.MRI,

            Modality.CT,

            Modality.XRAY,
        }:

            regions.append(

                OverlayRegion(

                    bbox=BoundingBox(

                        x1=0,
                        y1=0,

                        x2=int(w*0.30),
                        y2=h,
                    ),

                    confidence=0.90,

                    source="LEFT_PANEL",
                )
            )

        return regions

    def _contrast_regions(
        self,
        image: np.ndarray,
    ) -> list[OverlayRegion]:
        """
        Find high-contrast text-like regions.
        """

        thresh = cv2.adaptiveThreshold(

            image,

            255,

            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,

            cv2.THRESH_BINARY,

            31,

            15,
        )

        contours, _ = cv2.findContours(

            thresh,

            cv2.RETR_EXTERNAL,

            cv2.CHAIN_APPROX_SIMPLE,
        )

        regions = []

        for cnt in contours:

            x,y,w,h = cv2.boundingRect(
                cnt
            )

            area = w*h

            if area < 400:

                continue

            if w < 30:

                continue

            if h < 10:

                continue

            regions.append(

                OverlayRegion(

                    bbox=BoundingBox(

                        x1=int(x),
                        y1=int(y),

                        x2=int(x+w),
                        y2=int(y+h),
                    ),

                    confidence=0.60,

                    source="CONTRAST_REGION",
                )
            )

        return regions