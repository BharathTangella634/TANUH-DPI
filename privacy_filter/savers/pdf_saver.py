"""
pdf_saver.py
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

from ..savers.base import BaseSaver
from ..schemas.core import (
    MedicalArtifact,
)


class PDFSaver(BaseSaver):

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

        doc = fitz.open()

        pages = artifact.image

        if pages is None:

            raise RuntimeError(
                "No PDF pages."
            )

        if not isinstance(
            pages,
            list,
        ):

            pages = [pages]

        for page_arr in pages:

            img = Image.fromarray(
                page_arr
            )

            pdf_bytes = img.convert(
                "RGB"
            )

            temp = fitz.open()

            rect = fitz.Rect(

                0,

                0,

                img.width,

                img.height,
            )

            page = doc.new_page(

                width=img.width,

                height=img.height,
            )

            import io
            buf = io.BytesIO()
            pdf_bytes.save(buf, format="PNG")
            page.insert_image(rect, stream=buf.getvalue())

        doc.save(
            str(output_path)
        )