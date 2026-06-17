"""
pdf.py

PDF loader for MedDeID.

Supports:

    native text PDFs
    scanned PDFs
    hybrid PDFs

Returns:

    MedicalArtifact
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import fitz
import numpy as np
from PIL import Image

from ..loaders.base import BaseLoader
from ..schemas.core import (
    FileFormat,
    MedicalArtifact,
    Modality,
)

logger = logging.getLogger(__name__)


class PDFLoader(BaseLoader):
    """
    Universal PDF loader.

    Handles:

        native PDFs
        OCR/scanned PDFs
        mixed PDFs
    """

    SUPPORTED_FORMATS = {
        FileFormat.PDF
    }

    def supports(
        self,
        path: str | Path,
    ) -> bool:

        return (
            self.get_format(path)
            == FileFormat.PDF
        )

    def load(
        self,
        path: str | Path,
    ) -> MedicalArtifact:

        path = self.validate_path(path)

        self.ensure_supported(path)

        try:

            doc = fitz.open(
                str(path)
            )

        except Exception as exc:

            raise RuntimeError(
                f"Could not open PDF: {path}"
            ) from exc

        image_pages = self._render_pages(
            doc
        )

        metadata = self._extract_metadata(
            doc
        )

        artifact = MedicalArtifact(

            filepath=path,

            format=FileFormat.PDF,

            modality=Modality.DOCUMENT,

            image=image_pages,

            metadata=metadata,

            original_filename=path.name,
        )

        return artifact

    def _render_pages(
        self,
        doc: fitz.Document,
        dpi: int = 150,
    ) -> list[np.ndarray]:
        """
        Render PDF pages to images.

        Needed for:

            OCR detection
            burned-in PHI detection
            scanned PDF support
        """

        pages = []

        zoom = dpi / 72.0

        matrix = fitz.Matrix(
            zoom,
            zoom,
        )

        for page_idx in range(
            len(doc)
        ):

            try:

                page = doc[
                    page_idx
                ]

                pix = page.get_pixmap(
                    matrix=matrix,
                    alpha=False,
                )

                img = Image.open(
                    io.BytesIO(
                        pix.tobytes(
                            "png"
                        )
                    )
                )

                arr = np.asarray(
                    img
                )

                pages.append(
                    arr
                )

            except Exception as exc:

                logger.warning(
                    "PDF page render failed "
                    "(page=%d): %s",
                    page_idx,
                    exc,
                )

        return pages

    def _extract_metadata(
        self,
        doc: fitz.Document,
    ) -> dict[str, Any]:
        """
        Extract PDF metadata.
        """

        metadata = {}

        try:

            meta = doc.metadata

            if not meta:

                return metadata

            for key, value in meta.items():

                if value is None:

                    continue

                metadata[
                    str(key)
                ] = str(value)

        except Exception as exc:

            logger.warning(
                "PDF metadata extraction failed: %s",
                exc,
            )

        return metadata