"""
dicom_cleaner.py

DICOM metadata de-identification engine.

Implements a practical subset of the
DICOM PS3.15 Basic Application
Confidentiality Profile.

Responsibilities:

    remove PHI tags
    regenerate identifiers
    remove private tags
    normalize dates
    mark dataset as deidentified
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

from ..schemas.core import (
    PHIEntity,
    PHISource,
    RedactionMethod,
    RedactionReport,
)

logger = logging.getLogger(__name__)


# ============================================================
# DICOM PHI TAGS
# ============================================================

PHI_TAGS = {

    "PatientName",
    "PatientID",
    "IssuerOfPatientID",
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientSex",
    "PatientAge",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "AccessionNumber",
    "StudyID",
    "InstitutionName",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "RequestingPhysician",
    "OperatorsName",
    "PerformingPhysicianName",
    "StationName",
    "DeviceSerialNumber",
    "ProtocolName",

}


UID_TAGS = {

    "StudyInstanceUID",

    "SeriesInstanceUID",

    "SOPInstanceUID",

}


NON_TEXT_VRS = {

    "DA",
    "DT",
    "TM",

    "AS",   # Age String — constrained format (e.g. "044Y"); "REDACTED" is invalid

    "IS",
    "DS",

    "FL",
    "FD",

    "SL",
    "SS",

    "UL",
    "US",

    "UI",
}


class DicomCleaner:
    """
    DICOM metadata deidentifier.
    """

    def __init__(
        self,
        regenerate_uids: bool = True,
        remove_private_tags: bool = True,
        scrub_dates: bool = True,
    ):

        self.regenerate_uids = regenerate_uids

        self.remove_private_tags = remove_private_tags

        self.scrub_dates = scrub_dates

    def clean(
        self,
        ds: Dataset,
    ) -> tuple[Dataset, RedactionReport]:
        """
        Deidentify DICOM dataset.
        """

        report = RedactionReport()

        self._scrub_phi_tags(
            ds,
            report,
        )

        if self.regenerate_uids:

            self._regenerate_uids(
                ds,
                report,
            )

        if self.remove_private_tags:

            self._remove_private_tags(
                ds,
                report,
            )

        if self.scrub_dates:

            self._normalize_dates(
                ds,
                report,
            )

        self._mark_deidentified(
            ds
        )

        return ds, report

    def clean_file(
        self,
        input_path: str | Path,
        output_path: str | Path,
    ) -> RedactionReport:
        """
        File helper.
        """

        ds = pydicom.dcmread(
            str(input_path),
            force=True,
        )

        ds, report = self.clean(
            ds
        )

        Path(
            output_path
        ).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._ensure_file_meta(ds)

        ds.save_as(
            str(output_path),
            write_like_original=False,
        )

        return report

    @staticmethod
    def _ensure_file_meta(ds):
        """Guarantee the Dataset has a valid File Meta Information header."""
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid

        if not hasattr(ds, "file_meta") or ds.file_meta is None:
            ds.file_meta = pydicom.Dataset()

        if not getattr(ds.file_meta, "TransferSyntaxUID", None):
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        if not getattr(ds.file_meta, "MediaStorageSOPClassUID", None):
            ds.file_meta.MediaStorageSOPClassUID = getattr(
                ds, "SOPClassUID", "1.2.840.10008.5.1.4.1.1.7"
            )

        if not getattr(ds.file_meta, "MediaStorageSOPInstanceUID", None):
            ds.file_meta.MediaStorageSOPInstanceUID = getattr(
                ds, "SOPInstanceUID", generate_uid()
            )

    def _scrub_phi_tags(
        self,
        ds: Dataset,
        report: RedactionReport,
    ):

        for tag in PHI_TAGS:

            if not hasattr(
                ds,
                tag,
            ):
                continue

            try:

                elem = ds.data_element(
                    tag
                )

                vr = (
                    elem.VR
                    if elem
                    else ""
                )

                replacement = (
                    ""
                    if vr in NON_TEXT_VRS
                    else "REDACTED"
                )

                setattr(
                    ds,
                    tag,
                    replacement,
                )

                report.metadata_removed += 1

                report.detected_phi.append(

                    PHIEntity(

                        label=tag,

                        confidence=1.0,

                        source=PHISource.DICOM_TAG,

                        metadata_key=tag,
                    )
                )

            except Exception:

                logger.warning(
                    "Failed cleaning tag: %s",
                    tag,
                )

    def _regenerate_uids(
        self,
        ds: Dataset,
        report: RedactionReport,
    ):

        for uid_tag in UID_TAGS:

            if not hasattr(
                ds,
                uid_tag,
            ):
                continue

            try:

                setattr(
                    ds,
                    uid_tag,
                    generate_uid(),
                )

                report.redaction_methods.append(
                    RedactionMethod.UID_REGENERATION
                )

            except Exception:

                logger.warning(
                    "UID regeneration failed: %s",
                    uid_tag,
                )

    def _remove_private_tags(
        self,
        ds: Dataset,
        report: RedactionReport,
    ):

        try:

            before = len(
                list(ds.iterall())
            )

            ds.remove_private_tags()

            after = len(
                list(ds.iterall())
            )

            removed = before - after

            report.metadata_removed += max(
                removed,
                0,
            )

            report.redaction_methods.append(
                RedactionMethod.METADATA_STRIP
            )

        except Exception as exc:

            logger.warning(
                "Private tag removal failed: %s",
                exc,
            )

    def _normalize_dates(
        self,
        ds: Dataset,
        report: RedactionReport,
    ):
        """
        Normalize dates.

        Replace with canonical safe date.
        """

        safe_date = "19000101"

        for elem in ds.iterall():

            try:

                if elem.VR != "DA":

                    continue

                elem.value = safe_date

            except Exception:

                continue

    def _mark_deidentified(
        self,
        ds: Dataset,
    ):

        ds.PatientIdentityRemoved = "YES"

        ds.BurnedInAnnotation = "NO"

        ds.DeidentificationMethod = (

            "MedDeID DICOM Cleaner | "
            "metadata scrub + "
            "UID regeneration + "
            "private tag removal"
        )