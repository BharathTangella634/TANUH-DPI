"""
ocr_detector.py

Universal OCR detector for MedDeID.

Optimized for:

    MRI
    CT
    OCT
    Fundus
    Ultrasound
    DICOM screenshots
    PDFs

Backends:

    PaddleOCR
    Tesseract
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from ..schemas.core import (
    BoundingBox,
    MedicalArtifact,
    PHIEntity,
    PHISource,
)

from ..utils.image import (

    to_uint8,

    to_grayscale,
)

logger = logging.getLogger(__name__)

_TESS_EXE = (
    "tesseract.exe"
    if sys.platform == "win32"
    else "tesseract"
)


def _find_bundled_tesseract() -> str | None:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(
            Path(meipass) / "tesseract" / _TESS_EXE
        )
        candidates.append(
            Path(meipass) / _TESS_EXE
        )
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "tesseract" / _TESS_EXE)
    candidates.append(exe_dir / _TESS_EXE)
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(
            Path(appdir) / "usr" / "bin" / _TESS_EXE
        )
    for p in candidates:
        if p.is_file():
            tessdata = p.parent / "tessdata"
            if tessdata.is_dir():
                os.environ.setdefault(
                    "TESSDATA_PREFIX",
                    str(tessdata),
                )
            logger.debug(
                "Using bundled tesseract: %s", p
            )
            return str(p)
    return None


# ============================================================
# ABSTRACT BACKEND
# ============================================================

class OCRBackend(ABC):

    @abstractmethod
    def detect(
        self,
        image: np.ndarray,
    ) -> list[PHIEntity]:

        raise NotImplementedError


# ============================================================
# TESSERACT
# ============================================================

class TesseractBackend(OCRBackend):

    def __init__(self):

        tesseract_path = (
            _find_bundled_tesseract()
            or shutil.which("tesseract")
        )

        if tesseract_path is None:

            raise RuntimeError(

                "tesseract executable "
                "not found."
            )

        pytesseract.pytesseract.tesseract_cmd = (
            tesseract_path
        )

        self.config = (

            "--oem 3 "

            "--psm 6 "

            "-c preserve_interword_spaces=1"
        )

    def detect(
        self,
        image: np.ndarray,
    ) -> list[PHIEntity]:

        entities = []

        data = pytesseract.image_to_data(

            image,

            config=self.config,

            output_type=
            pytesseract.Output.DICT,
        )

        n = len(
            data["text"]
        )

        for i in range(n):

            text = str(
                data["text"][i]
            ).strip()

            if not text:

                continue

            try:

                conf = float(
                    data["conf"][i]
                )

            except Exception:

                conf = 0

            if conf < 10:

                continue

            x = int(
                data["left"][i]
            )

            y = int(
                data["top"][i]
            )

            w = int(
                data["width"][i]
            )

            h = int(
                data["height"][i]
            )

            entities.append(

                PHIEntity(

                    label="OCR_TEXT",

                    confidence=
                    conf / 100.0,

                    source=
                    PHISource.OCR,

                    text=text,

                    bbox=BoundingBox(

                        x1=x,
                        y1=y,

                        x2=x+w,
                        y2=y+h,
                    ),
                )
            )

        return entities


# ============================================================
# PADDLE
# ============================================================

class PaddleOCRBackend(OCRBackend):

    def __init__(self):

        from paddleocr import (
            PaddleOCR
        )

        self.model = PaddleOCR(

            use_angle_cls=True,

            lang="en",
        )

    def detect(
        self,
        image: np.ndarray,
    ) -> list[PHIEntity]:

        entities = []

        result = self.model.ocr(

            image,

            cls=True,
        )

        if not result:

            return entities

        for block in result:

            for line in block:

                bbox_pts, (

                    text,

                    conf,

                ) = line

                xs = [

                    p[0]

                    for p in bbox_pts
                ]

                ys = [

                    p[1]

                    for p in bbox_pts
                ]

                entities.append(

                    PHIEntity(

                        label="OCR_TEXT",

                        confidence=float(
                            conf
                        ),

                        source=
                        PHISource.OCR,

                        text=text,

                        bbox=BoundingBox(

                            x1=int(
                                min(xs)
                            ),

                            y1=int(
                                min(ys)
                            ),

                            x2=int(
                                max(xs)
                            ),

                            y2=int(
                                max(ys)
                            ),
                        ),
                    )
                )

        return entities


# ============================================================
# MAIN DETECTOR
# ============================================================
_OCR_SCALE = 2  # upscale factor applied in _preprocess


class OCRDetector:

    def __init__(
        self,
        backend: str = "tesseract",
    ):

        backend = backend.lower()

        if backend == "tesseract":

            self.backend = (
                TesseractBackend()
            )

        elif backend == "paddle":

            self.backend = (
                PaddleOCRBackend()
            )

        else:

            raise ValueError(

                f"Unsupported backend: "
                f"{backend}"
            )

    def detect(
        self,
        artifact: MedicalArtifact,
    ) -> list[PHIEntity]:

        if artifact.image is None:

            return []

        entities = []

        images = self._normalize_images(
            artifact.image
        )

        logger.debug(
            "[OCR] %d image(s) to scan",
            len(images),
        )

        for img_idx, img in enumerate(images):

            crops = self._corner_crops(img)

            logger.debug(
                "[OCR] image %d → %d crops",
                img_idx,
                len(crops),
            )

            for crop_idx, (crop, ox, oy) in enumerate(crops):

                processed = self._preprocess(crop)

                result = self.backend.detect(processed)

                # Translate each bbox from (2x-scaled crop space)
                # back to full-image pixel space.
                for entity in result:

                    if entity.bbox is not None:

                        entity.bbox = BoundingBox(

                            x1=int(entity.bbox.x1 / _OCR_SCALE) + ox,

                            y1=int(entity.bbox.y1 / _OCR_SCALE) + oy,

                            x2=int(entity.bbox.x2 / _OCR_SCALE) + ox,

                            y2=int(entity.bbox.y2 / _OCR_SCALE) + oy,
                        )

                entities.extend(result)

                logger.debug(
                    "[OCR] crop %d: %d entities",
                    crop_idx,
                    len(result),
                )

        entities = self._deduplicate(entities)

        logger.debug(
            "[OCR] %d unique entities after dedup",
            len(entities),
        )

        return entities

    # =====================================================

    def _normalize_images(
        self,
        image,
    ):

        if isinstance(image, list):

            return image

        if isinstance(image, np.ndarray):

            if image.ndim == 4:

                return list(image)

            return [image]

        return []

    # =====================================================

    def _corner_crops(
        self,
        image,
    ) -> list[tuple]:
        """
        Return [(crop, offset_x, offset_y), ...] for the TOP region only.

        Only the top strip is scanned — never the bottom corners.  On every
        supported modality the patient identity header (name, MRN, institution,
        date) sits at the very top, while the BOTTOM-LEFT region holds clinical
        MEASUREMENTS (D1/D2/D3, volume) and the BOTTOM-RIGHT / side panels hold
        scanner parameters.  Reading the bottom corners caused the PHI
        classifier to flag measurement numbers (e.g. "3.25", "14.19") as
        identifiers and mask clinically essential data.  Scanning a full-width
        top band keeps OCR aligned with the shape-based TextRegionDetector.
        """

        h, w = image.shape[:2]

        frac = 0.15

        ch = int(h * frac)

        return [
            (image[0:ch, 0:w], 0, 0),   # full-width TOP band — identity header
        ]

    # =====================================================

    def _preprocess(
        self,
        image,
    ):
        """
        Upscale 2x then binarize to black-text-on-white-background.

        Deliberately avoids CLAHE and sharpening: both amplify noise
        in the predominantly-dark corner regions of ophthalmic images
        (fundus, OCT) to the point where Tesseract reads fundus vessel
        patterns as text and misses the actual white patient-info overlay.

        The THRESH_BINARY_INV + THRESH_OTSU combination produces the
        right polarity (black text on white) for most medical overlays
        that use bright text on a dark background. The fallback inversion
        handles the opposite case (dark text on a light background, e.g.
        some CT/MRI screenshot DICOMs).
        """

        image = to_uint8(image)

        gray = to_grayscale(image)

        gray = cv2.resize(

            gray,

            None,

            fx=_OCR_SCALE,

            fy=_OCR_SCALE,

            interpolation=cv2.INTER_CUBIC,
        )

        # THRESH_BINARY_INV: bright pixels (text on dark bg) → black,
        # dark pixels (background) → white  →  black text on white ✓
        _, binary = cv2.threshold(

            gray,

            0,

            255,

            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
        )

        # If the result is mostly black the polarity is inverted
        # (original had dark text on light background).  Flip it back.
        if np.mean(binary) < 127:

            binary = cv2.bitwise_not(binary)

        return binary

    # =====================================================

    def _deduplicate(
        self,
        entities,
    ):

        seen = set()

        output = []

        for e in entities:

            key = (

                e.text,

                getattr(e.bbox, "x1", None),

                getattr(e.bbox, "y1", None),
            )

            if key in seen:

                continue

            seen.add(key)

            output.append(e)

        return output