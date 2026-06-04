"""
nifti_saver.py
"""

from __future__ import annotations

from pathlib import Path

import nibabel as nib

from ..savers.base import BaseSaver
from ..schemas.core import (
    MedicalArtifact,
)


class NiftiSaver(BaseSaver):

    def save(
        self,
        artifact: MedicalArtifact,
        output_path: str | Path,
    ):

        output_path = Path(
            output_path
        )

        output_path.parent.mkdir(

            parents=True,

            exist_ok=True,
        )

        import numpy as np

        image = artifact.image

        if image is None:
            raise RuntimeError("No volume data.")

        # After redaction the image may be a list of 2D slices
        # (normalize_images breaks 3D NIfTI volumes into per-slice arrays).
        # Re-stack along the depth axis to restore the original (H, W, D) shape.
        if isinstance(image, list):
            image = np.stack(image, axis=-1)

        # Prefer the cleaned in-memory NIfTI object (header already scrubbed);
        # update its data array with the (possibly redacted) pixel volume.
        nii_base = artifact.notes.get("_nii")
        if nii_base is not None:
            nii = nib.Nifti1Image(image, affine=nii_base.affine, header=nii_base.header)
        else:
            affine = artifact.notes.get("_affine", np.eye(4))
            nii = nib.Nifti1Image(image, affine=affine)

        nib.save(

            nii,

            str(output_path),
        )