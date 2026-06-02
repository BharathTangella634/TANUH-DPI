"""
image.py

Generic medical image loader for MedDeID.

Supports:

    PNG
    JPG
    JPEG
    TIFF
    BMP

Handles:

    grayscale images
    RGB images
    RGBA images
    16-bit medical images

Returns:

    MedicalArtifact
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ExifTags

from ..loaders.base import BaseLoader
from ..schemas.core import (
    FileFormat,
    MedicalArtifact,
    Modality,
)

logger = logging.getLogger(__name__)


class ImageLoader(BaseLoader):
    """
    Generic image loader.

    Used for:

        OCT exports
        Fundus scans
        Ultrasound screenshots
        MRI screenshots
        Histopathology
        Generic medical imaging
    """

    SUPPORTED_FORMATS = {

        FileFormat.PNG,

        FileFormat.JPG,

        FileFormat.JPEG,

        FileFormat.TIFF,

        FileFormat.BMP,
    }

    def supports(
        self,
        path: str | Path,
    ) -> bool:

        fmt = self.get_format(path)

        return fmt in self.SUPPORTED_FORMATS

    def load(
        self,
        path: str | Path,
    ) -> MedicalArtifact:

        path = self.validate_path(path)

        self.ensure_supported(path)

        image = self._load_image(path)

        metadata = self._extract_metadata(path)

        modality = self._infer_modality(
            path,
            metadata,
        )

        artifact = MedicalArtifact(

            filepath=path,

            format=self.get_format(path),

            modality=modality,

            image=image,

            metadata=metadata,

            original_filename=path.name,
        )

        return artifact

    def _load_image(
        self,
        path: Path,
    ) -> np.ndarray:
        """
        Load image preserving native bit depth.

        Uses cv2.IMREAD_UNCHANGED
        to preserve:

            8-bit

            16-bit

            alpha channels

            grayscale
        """

        image = cv2.imread(
            str(path),
            cv2.IMREAD_UNCHANGED,
        )

        if image is None:

            raise RuntimeError(
                f"Could not read image: {path}"
            )

        return np.asarray(image)

    def _extract_metadata(
        self,
        path: Path,
    ) -> dict[str, Any]:
        """
        Extract EXIF metadata.

        Returns empty dict
        if unavailable.
        """

        metadata = {}

        try:

            img = Image.open(path)

            exif = img.getexif()

            if not exif:

                return metadata

            for tag_id, value in exif.items():

                tag_name = ExifTags.TAGS.get(
                    tag_id,
                    str(tag_id),
                )

                try:

                    metadata[tag_name] = str(value)

                except Exception:

                    continue

        except Exception as exc:

            logger.debug(
                "EXIF extraction failed: %s",
                exc,
            )

        return metadata

    def _infer_modality(
        self,
        path: Path,
        metadata: dict[str, Any],
    ) -> Modality:
        """
        Infer modality from filename + metadata.

        Generic images do not have
        reliable modality fields.

        Uses heuristics.
        """

        filename = path.name.lower()

        if "oct" in filename:

            return Modality.OCT

        if "fundus" in filename:

            return Modality.FUNDUS

        if "retina" in filename:

            return Modality.FUNDUS

        if "ultrasound" in filename:

            return Modality.ULTRASOUND

        if "usg" in filename:

            return Modality.ULTRASOUND

        if "mri" in filename:

            return Modality.MRI

        if "ct" in filename:

            return Modality.CT

        if "xray" in filename:

            return Modality.XRAY

        if "histopath" in filename:

            return Modality.HISTOPATH

        if "wsi" in filename:

            return Modality.HISTOPATH

        modality_meta = str(
            metadata.get(
                "Modality",
                "",
            )
        ).upper()

        if modality_meta:

            return self.infer_modality(
                {"Modality": modality_meta}
            )

        return Modality.UNKNOWN