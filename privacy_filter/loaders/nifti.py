"""
nifti.py

NIfTI loader for MedDeID.

Supports:

    .nii
    .nii.gz

Handles:

    3D volumes
    4D time-series
    segmentation masks
    compressed NIfTI

Returns:

    MedicalArtifact
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from ..loaders.base import BaseLoader
from ..schemas.core import (
    FileFormat,
    MedicalArtifact,
    Modality,
)

logger = logging.getLogger(__name__)


class NiftiLoader(BaseLoader):
    """
    Universal NIfTI loader.

    Supports:

        .nii
        .nii.gz
    """

    SUPPORTED_FORMATS = {
        FileFormat.NIFTI
    }

    def supports(
        self,
        path: str | Path,
    ) -> bool:

        path = Path(path)

        name = path.name.lower()

        return (
            name.endswith(".nii")
            or name.endswith(".nii.gz")
        )

    def load(
        self,
        path: str | Path,
    ) -> MedicalArtifact:

        path = self.validate_path(path)

        self.ensure_supported(path)

        try:

            nii = nib.load(
                str(path)
            )

        except Exception as exc:

            raise RuntimeError(
                f"Failed to load NIfTI: {path}"
            ) from exc

        image = self._extract_image(
            nii
        )

        metadata = self._extract_metadata(
            nii
        )

        modality = self._infer_modality(
            path,
            metadata,
        )

        artifact = MedicalArtifact(

            filepath=path,

            format=FileFormat.NIFTI,

            modality=modality,

            image=image,

            metadata=metadata,

            original_filename=path.name,

            # Preserve the affine so NiftiSaver can write a geometrically
            # correct output without losing spatial orientation.
            notes={"_affine": nii.affine},
        )

        return artifact

    def _extract_image(
        self,
        nii: nib.Nifti1Image,
    ) -> np.ndarray:
        """
        Extract image volume.

        Preserves:

            3D
            4D
            float volumes
            integer masks
        """

        try:

            image = nii.get_fdata()

        except Exception as exc:

            raise RuntimeError(
                "NIfTI image extraction failed."
            ) from exc

        return np.asarray(
            image
        )

    def _extract_metadata(
        self,
        nii: nib.Nifti1Image,
    ) -> dict[str, Any]:
        """
        Extract NIfTI header metadata.
        """

        metadata = {}

        try:

            header = nii.header

            for key in header.keys():

                try:

                    value = header[key]

                    if hasattr(
                        value,
                        "tolist"
                    ):

                        value = value.tolist()

                    metadata[
                        str(key)
                    ] = str(value)

                except Exception:

                    continue

        except Exception as exc:

            logger.warning(
                "Header extraction failed: %s",
                exc,
            )

        return metadata

    def _infer_modality(
        self,
        path: Path,
        metadata: dict[str, Any],
    ) -> Modality:
        """
        Infer modality.

        NIfTI usually lacks
        standardized modality fields.

        Uses:

            filename heuristics
            header descriptions
        """

        filename = path.name.lower()

        if "mri" in filename:

            return Modality.MRI

        if "mr" in filename:

            return Modality.MRI

        if "ct" in filename:

            return Modality.CT

        if "pet" in filename:

            return Modality.PET

        if "xray" in filename:

            return Modality.XRAY

        desc = str(
            metadata.get(
                "descrip",
                "",
            )
        ).lower()

        if "mri" in desc:

            return Modality.MRI

        if "ct" in desc:

            return Modality.CT

        if "pet" in desc:

            return Modality.PET

        return Modality.UNKNOWN