"""
dicom.py

DICOM loader for MedDeID.

Supports:

    - single-frame DICOM
    - multi-frame DICOM
    - RGB DICOM
    - grayscale DICOM
    - compressed DICOM (when handlers installed)

Returns:

    MedicalArtifact
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

from ..loaders.base import BaseLoader
from ..schemas.core import (
    FileFormat,
    MedicalArtifact,
    Modality,
)

logger = logging.getLogger(__name__)


class DicomLoader(BaseLoader):
    """
    Universal DICOM loader.
    """

    SUPPORTED_FORMATS = {
        FileFormat.DICOM
    }

    def supports(
        self,
        path: str | Path,
    ) -> bool:

        fmt = self.get_format(path)

        return fmt == FileFormat.DICOM

    def load(
        self,
        path: str | Path,
    ) -> MedicalArtifact:

        path = self.validate_path(path)

        self.ensure_supported(path)

        try:
            ds = pydicom.dcmread(
                str(path),
                force=True,
            )

        except InvalidDicomError as exc:

            raise ValueError(
                f"Invalid DICOM file: {path}"
            ) from exc

        except Exception as exc:

            raise RuntimeError(
                f"DICOM read failed: {path}"
            ) from exc

        if not hasattr(ds.file_meta, "TransferSyntaxUID") or ds.file_meta.TransferSyntaxUID is None:
            from pydicom.uid import ImplicitVRLittleEndian
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

        metadata = self._extract_metadata(ds)

        modality = self._infer_modality(ds)

        image = self._extract_pixels(ds)

        artifact = MedicalArtifact(

            filepath=path,

            format=FileFormat.DICOM,

            modality=modality,

            image=image,

            metadata=metadata,

            original_filename=path.name,

            # Preserve the full pydicom Dataset so the saver
            # can write it back with updated pixel data intact.
            notes={"_ds": ds},
        )

        return artifact

    def _extract_metadata(
        self,
        ds: Dataset,
    ) -> dict[str, Any]:
        """
        Extract metadata into plain dictionary.

        Converts pydicom objects into
        serializable values.
        """

        metadata: dict[str, Any] = {}

        for elem in ds:

            try:

                keyword = elem.keyword

                if not keyword:
                    continue

                if keyword == "PixelData":
                    continue

                metadata[keyword] = str(elem.value)

            except Exception:

                continue

        return metadata

    def _infer_modality(
        self,
        ds: Dataset,
    ) -> Modality:
        """
        DICOM modality detection.
        """

        modality = str(
            getattr(
                ds,
                "Modality",
                "",
            )
        ).upper()

        mapping = {

            "MR": Modality.MRI,

            "CT": Modality.CT,

            "US": Modality.ULTRASOUND,

            "DX": Modality.XRAY,

            "CR": Modality.XRAY,

            "PT": Modality.PET,

            "OCT": Modality.OCT,
        }

        return mapping.get(
            modality,
            Modality.UNKNOWN,
        )

    def _extract_pixels(
        self,
        ds: Dataset,
    ) -> np.ndarray | list[np.ndarray] | None:
        """
        Safely extract pixel array.

        Supports:

            2D
            3D
            multi-frame
            RGB
        """

        if "PixelData" not in ds:

            logger.warning(
                "No pixel data found."
            )

            return None

        try:

            pixels = ds.pixel_array

        except Exception as exc:

            logger.warning(
                "Pixel extraction failed: %s",
                exc,
            )

            return None

        try:

            pixels = np.asarray(
                pixels
            )

        except Exception:

            return None

        return pixels