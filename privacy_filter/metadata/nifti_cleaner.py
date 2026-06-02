"""
nifti_cleaner.py

NIfTI metadata de-identification.

Supports:

    .nii
    .nii.gz

Responsibilities:

    scrub PHI-prone headers
    normalize provenance fields
    preserve image volume
"""

from __future__ import annotations

import logging
from pathlib import Path

import nibabel as nib

from ..schemas.core import (
    PHIEntity,
    PHISource,
    RedactionMethod,
    RedactionReport,
)

logger = logging.getLogger(__name__)


# ============================================================
# HEADER FIELDS WITH PHI RISK
# ============================================================

PHI_FIELDS = {

    "descrip",

    "aux_file",

    "db_name",

    "intent_name",
}


class NiftiCleaner:
    """
    NIfTI metadata cleaner.
    """

    def clean(
        self,
        nii: nib.Nifti1Image,
    ) -> tuple[
        nib.Nifti1Image,
        RedactionReport,
    ]:
        """
        Clean NIfTI object.
        """

        report = RedactionReport()

        header = nii.header

        for field in PHI_FIELDS:

            if field not in header:

                continue

            try:

                old_value = str(
                    header[field]
                )

                report.detected_phi.append(

                    PHIEntity(

                        label=field,

                        confidence=1.0,

                        source=PHISource.NIFTI_HEADER,

                        metadata_key=field,

                        metadata_value=old_value,
                    )
                )

                header[field] = b""

                report.metadata_removed += 1

            except Exception:

                logger.warning(
                    "Failed cleaning "
                    "NIfTI header field: %s",
                    field,
                )

        report.redaction_methods.append(

            RedactionMethod.METADATA_STRIP
        )

        return nii, report

    def clean_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> RedactionReport:
        """
        File helper.
        """

        try:

            nii = nib.load(
                str(input_path)
            )

        except Exception as exc:

            raise RuntimeError(
                f"Could not load "
                f"NIfTI: {input_path}"
            ) from exc

        nii, report = self.clean(
            nii
        )

        output_path = Path(
            output_path
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        nib.save(
            nii,
            str(output_path),
        )

        logger.info(

            "NIfTI cleaned → %s",

            output_path,
        )

        return report