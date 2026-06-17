"""
exif_cleaner.py

Metadata cleaner for image files.

Supports:

    PNG
    JPG
    JPEG
    TIFF
    BMP

Responsibilities:

    remove EXIF
    remove IPTC
    remove XMP
    strip PNG text chunks
    preserve pixel content
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..schemas.core import (
    PHIEntity,
    PHISource,
    RedactionMethod,
    RedactionReport,
)

logger = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = {

    ".png",

    ".jpg",
    ".jpeg",

    ".tif",
    ".tiff",

    ".bmp",
}


class EXIFCleaner:
    """
    Generic image metadata cleaner.
    """

    def clean_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> RedactionReport:
        """
        Clean image metadata.

        Pixel data is preserved.

        Metadata is removed.
        """

        input_path = Path(
            input_path
        )

        output_path = Path(
            output_path
        )

        suffix = (
            input_path
            .suffix
            .lower()
        )

        if suffix not in SUPPORTED_SUFFIXES:

            raise ValueError(
                f"Unsupported image format: "
                f"{suffix}"
            )

        report = RedactionReport()

        try:

            img = Image.open(
                input_path
            )

        except Exception as exc:

            raise RuntimeError(
                f"Could not open image: "
                f"{input_path}"
            ) from exc

        metadata_detected = self._collect_metadata(
            img
        )

        for item in metadata_detected:

            report.detected_phi.append(
                item
            )

        report.metadata_removed += len(
            metadata_detected
        )

        self._save_clean_image(

            img,

            output_path,

            suffix,
        )

        report.redaction_methods.append(
            RedactionMethod.METADATA_STRIP
        )

        return report

    def _collect_metadata(
        self,
        img: Image.Image,
    ) -> list[PHIEntity]:
        """
        Detect available metadata fields.
        """

        entities = []

        # ---------- EXIF ----------

        try:

            exif = img.getexif()

            if exif:

                for tag_id, value in exif.items():

                    entities.append(

                        PHIEntity(

                            label=f"EXIF:{tag_id}",

                            confidence=1.0,

                            source=PHISource.EXIF,

                            metadata_key=str(
                                tag_id
                            ),

                            metadata_value=str(
                                value
                            ),
                        )
                    )

        except Exception:

            pass

        # ---------- PNG text/XMP ----------

        try:

            info = getattr(
                img,
                "info",
                {},
            )

            # Ignore standard technical image attributes that do not contain PHI.
            # "exif" in info is a raw bytes blob; actual tags are parsed via getexif().
            IGNORE_KEYS = {
                "jfif", "jfif_version", "jfif_unit", "jfif_density",
                "dpi", "icc_profile", "quality", "progressive",
                "progression", "adobe", "adobe_transform", "bits",
                "chromaticity", "aspect", "exif", "transparency"
            }

            for key, value in info.items():
                if str(key).lower() in IGNORE_KEYS:
                    continue

                entities.append(

                    PHIEntity(

                        label=f"INFO:{key}",

                        confidence=1.0,

                        source=PHISource.EXIF,

                        metadata_key=str(
                            key
                        ),

                        metadata_value=str(
                            value
                        ),
                    )
                )

        except Exception:

            pass

        return entities

    def _save_clean_image(
        self,
        img: Image.Image,
        output_path: Path,
        suffix: str,
    ):
        """
        Save clean image.

        Removes:

            EXIF
            XMP
            IPTC
            PNG text chunks
        """

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        clean = Image.new(

            img.mode,

            img.size,
        )

        clean.putdata(
            list(
                img.getdata()
            )
        )

        save_kwargs = {}

        # Explicitly remove EXIF.

        if suffix in {

            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
        }:

            save_kwargs[
                "exif"
            ] = b""

        clean.save(

            output_path,

            **save_kwargs,
        )

        logger.info(

            "Image metadata stripped → %s",

            output_path,
        )