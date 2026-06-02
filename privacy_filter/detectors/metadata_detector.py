"""
metadata_detector.py

Metadata PHI detector for MedDeID.

Detects PHI inside:

    DICOM headers
    NIfTI headers
    EXIF
    PDF metadata

Returns:

    list[PHIEntity]
"""

from __future__ import annotations

import logging
import re

from ..schemas.core import (
    MedicalArtifact,
    PHIEntity,
    PHISource,
)

logger = logging.getLogger(__name__)


# ============================================================
# HIGH-RISK METADATA KEYS
# ============================================================

KNOWN_PHI_KEYS = {

    # ---------- DICOM ----------

    "PatientName",
    "PatientID",
    "IssuerOfPatientID",       # institution patient-registry ID
    "OtherPatientIDs",
    "OtherPatientNames",
    "PatientBirthDate",
    "PatientBirthTime",
    "PatientSex",
    "PatientAge",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "InstitutionName",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "RequestingPhysician",
    "OperatorsName",
    "PerformingPhysicianName",
    "AccessionNumber",
    "StudyID",
    "DeviceSerialNumber",
    "StationName",

    # ---------- NIfTI ----------

    "descrip",
    "aux_file",
    "db_name",
    "intent_name",

    # ---------- PDF ----------

    "author",
    "creator",
    "producer",
    "title",
    "subject",
}


# Values written by the cleaner to indicate a field has been scrubbed.
# A field whose value is one of these should NOT be re-flagged as PHI.
_SAFE_VALUES = {
    "REDACTED",
    "",
    "b''",         # empty bytes repr from NIfTI cleaner
    "b'\\x00'",
    "19000101",    # canonical safe DICOM date
    "19000100",
    "000000",
    "0",
    "0.0",
    "NO",          # BurnedInAnnotation = NO
    "YES",         # PatientIdentityRemoved = YES
}


# Technical DICOM fields that are never patient PHI.
# Regex-based detection (date, UID, MRN patterns) is skipped for these.
_DICOM_TECHNICAL_KEYS = {
    # Unique identifiers — regenerated, not patient-linked
    "SOPClassUID", "SOPInstanceUID",
    "StudyInstanceUID", "SeriesInstanceUID",
    "TransferSyntaxUID", "ImplementationClassUID",
    "ReferencedSOPClassUID", "ReferencedSOPInstanceUID",
    # Dates/times — normalised to safe canonical values by DicomCleaner
    "StudyDate", "StudyTime",
    "SeriesDate", "SeriesTime",
    "AcquisitionDate", "AcquisitionTime",
    "ContentDate", "ContentTime",
    "InstanceCreationDate", "InstanceCreationTime",
    # Image / scanner parameters
    "ImageType", "Modality", "Manufacturer", "ManufacturerModelName",
    "Rows", "Columns", "BitsAllocated", "BitsStored", "HighBit",
    "PixelRepresentation", "SamplesPerPixel", "PhotometricInterpretation",
    "PixelSpacing", "ImagerPixelSpacing", "WindowCenter", "WindowWidth",
    "RescaleIntercept", "RescaleSlope", "RescaleType",
    "ImplementationVersionName", "SpecificCharacterSet",
    "MediaStorageSOPClassUID", "MediaStorageSOPInstanceUID",
    # De-identification flags set by our own cleaner — not PHI
    "PatientIdentityRemoved", "BurnedInAnnotation", "DeidentificationMethod",
    # CR / DR scanner equipment identifiers
    "PlateID", "CassetteID", "DetectorID", "DetectorType",
    "BodyPartExamined", "ViewPosition", "ExposureIndex",
    "DeviationIndex", "TargetExposureIndex",
    "KVP", "ExposureTime", "XRayTubeCurrent", "Exposure",
    "FocalSpots", "AnodeTargetMaterial", "DistanceSourceToDetector",
    "DistanceSourceToPatient", "FieldOfViewShape",
    "ProtocolName", "PerformedProcedureStepDescription",
    "RequestedProcedureDescription",
    # Software / equipment metadata
    "SoftwareVersions", "ImplementationVersionName",
    "DeviceSerialNumber",
    # TIFF image structure fields (not PHI)
    "StripByteCounts", "StripOffsets", "RowsPerStrip",
    "BitsPerSample", "Compression", "XResolution", "YResolution",
    "ResolutionUnit", "Orientation", "PlanarConfiguration",
    "TileWidth", "TileLength", "TileByteCounts", "TileOffsets",
    "ImageWidth", "ImageLength", "JPEGInterchangeFormat",
    "JPEGInterchangeFormatLength",
    # Procedure / acquisition dates and times
    "PerformedProcedureStepStartDate", "PerformedProcedureStepStartTime",
    "PerformedProcedureStepEndDate",   "PerformedProcedureStepEndTime",
    "ScheduledProcedureStepStartDate", "ScheduledProcedureStepStartTime",
    "TimeOfSecondaryCapture", "DateOfSecondaryCapture",
    "Laterality",
    # NIfTI geometry / numeric parameter fields (none are patient PHI)
    "intent_p1", "intent_p2", "intent_p3",
    "vox_offset", "cal_max", "cal_min", "scl_slope", "scl_inter",
    "quatern_b", "quatern_c", "quatern_d",
    "qoffset_x", "qoffset_y", "qoffset_z",
    "srow_x", "srow_y", "srow_z",
    "pixdim", "dim", "sizeof_hdr", "data_type", "bitpix",
    "slice_start", "slice_end", "slice_code", "slice_duration",
    "toffset", "xyzt_units", "dim_info", "intent_code",
    "qform_code", "sform_code",
    "glmax", "glmin",
}


# ============================================================
# REGEX PATTERNS
# ============================================================

DATE_PATTERN = re.compile(

    r"\d{4}[-/]?\d{2}[-/]?\d{2}"

)

MRN_PATTERN = re.compile(

    r"\b\d{5,15}\b"

)

UID_PATTERN = re.compile(

    r"^\d+(\.\d+)+$"

)


class MetadataDetector:
    """
    Metadata PHI detector.
    """

    def detect(
        self,
        artifact: MedicalArtifact,
    ) -> list[PHIEntity]:
        """
        Detect PHI inside artifact metadata.
        """

        entities = []

        metadata = artifact.metadata

        if not metadata:

            return entities

        for key, value in metadata.items():

            value_str = str(
                value
            ).strip()

            if not value_str:

                continue

            detection = self._classify(

                key,

                value_str,
            )

            if detection is None:

                continue

            entities.append(
                detection
            )

        return entities

    def _classify(
        self,
        key: str,
        value: str,
    ) -> PHIEntity | None:
        """
        Metadata classification logic.
        """

        key_norm = key.strip()

        # --------------------------------------------------
        # Known PHI fields — but only if NOT already scrubbed.
        # After de-identification the value is "REDACTED",
        # "19000101", or empty; re-flagging those is a false positive.
        # --------------------------------------------------

        if key_norm in KNOWN_PHI_KEYS:

            if value in _SAFE_VALUES or not value:
                return None

            return PHIEntity(

                label=key_norm,

                confidence=1.0,

                source=self._infer_source(key_norm),

                metadata_key=key_norm,

                metadata_value=value,
            )

        # Technical DICOM fields are never patient PHI — skip regex.
        if key_norm in _DICOM_TECHNICAL_KEYS:
            return None

        # Values written by the cleaner are safe — skip all regex.
        if value in _SAFE_VALUES:
            return None

        # --------------------------------------------------
        # Date-like values in unexpected fields
        # --------------------------------------------------

        if DATE_PATTERN.search(value):

            return PHIEntity(

                label="DATE",

                confidence=0.80,

                source=PHISource.RULE,

                metadata_key=key_norm,

                metadata_value=value,
            )

        # --------------------------------------------------
        # UID-like identifiers in unexpected fields
        # --------------------------------------------------

        if UID_PATTERN.match(value):

            return PHIEntity(

                label="UID",

                confidence=0.90,

                source=PHISource.RULE,

                metadata_key=key_norm,

                metadata_value=value,
            )

        # --------------------------------------------------
        # MRN / numeric identifiers in unexpected fields
        # --------------------------------------------------

        if MRN_PATTERN.search(value):

            return PHIEntity(

                label="NUMERIC_IDENTIFIER",

                confidence=0.70,

                source=PHISource.RULE,

                metadata_key=key_norm,

                metadata_value=value,
            )

        return None

    def _infer_source(
        self,
        key: str,
    ) -> PHISource:
        """
        Infer metadata source.
        """

        key_lower = key.lower()

        # DICOM

        if key.startswith(
            "Patient"
        ):

            return PHISource.DICOM_TAG

        if "institution" in key_lower:

            return PHISource.DICOM_TAG

        if "study" in key_lower:

            return PHISource.DICOM_TAG

        # NIfTI

        if key_lower in {

            "descrip",

            "aux_file",

            "intent_name",

            "db_name",
        }:

            return PHISource.NIFTI_HEADER

        # EXIF / PDF

        return PHISource.EXIF