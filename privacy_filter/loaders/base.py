"""
base.py

Abstract loader contract for MedDeID.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..schemas.core import (
    FileFormat,
    MedicalArtifact,
    Modality,
)


class BaseLoader(ABC):
    """
    Abstract loader interface.

    Every loader must:

        validate input
        parse file
        infer modality
        return MedicalArtifact
    """

    SUPPORTED_FORMATS: set[FileFormat] = set()

    def __call__(
        self,
        path: str | Path,
    ) -> MedicalArtifact:

        return self.load(path)

    @abstractmethod
    def load(
        self,
        path: str | Path,
    ) -> MedicalArtifact:
        """
        Load file into MedicalArtifact.
        """
        raise NotImplementedError

    @abstractmethod
    def supports(
        self,
        path: str | Path,
    ) -> bool:
        """
        Return True if loader supports file.
        """
        raise NotImplementedError

    def validate_path(
        self,
        path: str | Path,
    ) -> Path:
        """
        Common validation.
        """

        path = Path(path)

        if not path.exists():

            raise FileNotFoundError(
                f"File does not exist: {path}"
            )

        if not path.is_file():

            raise ValueError(
                f"Expected file, got: {path}"
            )

        return path

    def infer_modality(
        self,
        metadata: dict | None = None,
    ) -> Modality:
        """
        Generic modality inference.

        Can be overridden by subclasses.
        """

        if not metadata:

            return Modality.UNKNOWN

        modality = str(
            metadata.get(
                "Modality",
                "",
            )
        ).upper()

        mapping = {

            "MR": Modality.MRI,
            "MRI": Modality.MRI,

            "CT": Modality.CT,

            "US": Modality.ULTRASOUND,
            "ULTRASOUND": Modality.ULTRASOUND,

            "DX": Modality.XRAY,
            "CR": Modality.XRAY,
            "XRAY": Modality.XRAY,

            "OCT": Modality.OCT,

            "FUNDUS": Modality.FUNDUS,

            "PT": Modality.PET,
            "PET": Modality.PET,
        }

        return mapping.get(
            modality,
            Modality.UNKNOWN,
        )

    def get_format(
        self,
        path: str | Path,
    ) -> FileFormat:
        """
        Robust file-format detection.

        Handles:

            .nii.gz
            .dcm
            .png
            .pdf
            etc.
        """

        filename = Path(
            path
        ).name.lower()

        # -------- compound extensions --------

        if filename.endswith(
            ".nii.gz"
        ):
            return FileFormat.NIFTI

        # -------- standard extensions --------

        suffix = Path(
            filename
        ).suffix.lower()

        mapping = {

            ".dcm": FileFormat.DICOM,
            ".dicom": FileFormat.DICOM,

            ".nii": FileFormat.NIFTI,

            ".png": FileFormat.PNG,

            ".jpg": FileFormat.JPG,
            ".jpeg": FileFormat.JPEG,

            ".tif": FileFormat.TIFF,
            ".tiff": FileFormat.TIFF,

            ".bmp": FileFormat.BMP,

            ".pdf": FileFormat.PDF,

            ".docx": FileFormat.DOCX,

            ".txt": FileFormat.TXT,
        }

        return mapping.get(
            suffix,
            FileFormat.UNKNOWN,
        )

    def ensure_supported(
        self,
        path: str | Path,
    ) -> None:
        """
        Verify loader compatibility.
        """

        if not self.supports(path):

            fmt = self.get_format(
                path
            )

            raise ValueError(
                f"{self.name} "
                f"does not support "
                f"{fmt.value}"
            )

    @property
    def name(
        self,
    ) -> str:
        """
        Human-readable loader name.
        """

        return self.__class__.__name__