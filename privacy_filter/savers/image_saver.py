"""
image_saver.py
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..savers.base import BaseSaver
from ..schemas.core import (
    MedicalArtifact,
)


class ImageSaver(BaseSaver):

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

        image = artifact.image

        if image is None:

            raise RuntimeError(
                "No image data."
            )

        if isinstance(
            image,
            list,
        ):

            raise RuntimeError(
                "Use video/stack saver "
                "for image lists."
            )

        success = cv2.imwrite(

            str(output_path),

            np.asarray(image),
        )

        if not success:

            raise RuntimeError(
                "Image save failed."
            )