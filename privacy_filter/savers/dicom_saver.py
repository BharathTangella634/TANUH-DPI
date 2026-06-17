"""
dicom_saver.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom

from ..savers.base import BaseSaver
from ..schemas.core import (
    MedicalArtifact,
)


class DicomSaver(BaseSaver):

    def save(
        self,
        artifact: MedicalArtifact,
        output_path: str | Path,
    ):

        output_path = Path(output_path)

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        ds = artifact.notes.get("_ds")

        if ds is None:

            raise RuntimeError(
                "DICOM Dataset not found in artifact.notes['_ds']. "
                "Ensure DicomLoader populated it."
            )

        if artifact.image is not None:

            self._write_pixels(ds, artifact.image)

        ds.save_as(
            str(output_path),
            write_like_original=False,
        )

    # ----------------------------------------------------------

    def _write_pixels(
        self,
        ds: pydicom.Dataset,
        image: np.ndarray,
    ):
        """
        Write the (possibly redacted) pixel array back into the Dataset.

        Handles:
            2D grayscale
            2D RGB
            3D multi-frame
        """

        arr = np.asarray(image)

        if arr.ndim == 2:

            ds.Rows, ds.Columns = arr.shape

            ds.SamplesPerPixel = 1

            ds.PhotometricInterpretation = "MONOCHROME2"

        elif arr.ndim == 3 and arr.shape[2] in (3, 4):

            # RGB or RGBA — drop alpha channel if present
            if arr.shape[2] == 4:

                arr = arr[:, :, :3]

            ds.Rows, ds.Columns = arr.shape[:2]

            ds.SamplesPerPixel = 3

            ds.PhotometricInterpretation = "RGB"

            ds.PlanarConfiguration = 0

        elif arr.ndim == 3:

            # Multi-frame grayscale (frames, rows, cols)
            frames, rows, cols = arr.shape

            ds.NumberOfFrames = frames

            ds.Rows = rows

            ds.Columns = cols

            ds.SamplesPerPixel = 1

            ds.PhotometricInterpretation = "MONOCHROME2"

        else:

            return

        if arr.dtype == np.uint16:

            ds.BitsAllocated = 16

            ds.BitsStored = 16

            ds.HighBit = 15

            ds.PixelRepresentation = 0

        else:

            arr = arr.astype(np.uint8)

            ds.BitsAllocated = 8

            ds.BitsStored = 8

            ds.HighBit = 7

            ds.PixelRepresentation = 0

        ds.PixelData = arr.tobytes()

        # Remove any compressed transfer syntax so the new raw data is valid.
        try:

            from pydicom.uid import ExplicitVRLittleEndian

            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        except Exception:

            pass
