"""
phi_detector.py

PHI classification layer for MedDeID.

Converts:

    OCR detections
    metadata detections

into:

    grouped PHI entities.

Supports:

    patient names
    DOB
    MRN
    accession IDs
    physician names
    dates
    hospital identifiers
"""

from __future__ import annotations

import logging
import re

from ..schemas.core import (
    BoundingBox,
    PHIEntity,
    PHISource,
)

logger = logging.getLogger(__name__)


# ============================================================
# MEDICAL PHI KEYWORDS
# ============================================================

KEYWORDS = {

    "PATIENT",

    "NAME",

    "DOB",

    "BIRTH",

    "MRN",

    "ID",

    "PATIENTID",

    "ACCESSION",

    "STUDY",

    "HOSPITAL",

    "PHYSICIAN",

    "DOCTOR",

    "SEX",

    "AGE",
}


# ============================================================
# REGEX RULES
# ============================================================

DATE_PATTERN = re.compile(

    r"""
    (
        \d{4}[-/]\d{2}[-/]\d{2}
        |
        \d{2}[-/]\d{2}[-/]\d{4}
        |
        \d{8}
    )
    """,

    re.VERBOSE,
)

IDENTIFIER_PATTERN = re.compile(

    r"""
    (
        \b\d{5,20}\b
        |
        \b[A-Z]{2,10}\d{3,20}\b
        |
        \b\d+[A-Z]+\d*\b
    )
    """,

    re.VERBOSE,
)

UID_PATTERN = re.compile(
    r"^\d+(\.\d+)+$"
)

AGE_PATTERN = re.compile(

    r"\b\d{1,3}[YMDF]\b",

    re.IGNORECASE,
)

NAME_PATTERN = re.compile(

    # Two or more alpha words separated by space, comma, or hyphen.
    # Handles: "John Doe", "TIWARI,DEVANAND", "SMITH, JOHN", "MARY-ANN"
    r"^[A-Za-z]+(?:[,\s\-]+[A-Za-z]+)+$"

)


# ============================================================
# DETECTOR
# ============================================================

class PHIDetector:
    """
    PHI semantic detector.
    """

    def __init__(

        self,

        confidence_threshold: float = 0.50,
    ):

        self.threshold = (
            confidence_threshold
        )

    def detect(
        self,
        entities: list[PHIEntity],
    ) -> list[PHIEntity]:
        """
        Main classification pipeline.
        """

        entities = self._expand_context(
            entities
        )

        output = []

        for entity in entities:

            result = self._classify(
                entity
            )

            if result is None:

                continue

            if result.confidence < self.threshold:

                continue

            output.append(
                result
            )

        return output

    # =======================================================
    # CONTEXT EXPANSION
    # =======================================================

    def _expand_context(
        self,
        entities: list[PHIEntity],
    ) -> list[PHIEntity]:

        expanded = []

        i = 0

        while i < len(entities):

            current = entities[i]

            text = (
                current.text or ""
            ).strip()

            clean_upper = (

            text.upper()

            .replace(":", "")

            .replace("-", "")

            .strip()
            )

            if clean_upper in KEYWORDS:

                merged_text = text

                merged_bbox = current.bbox

                j = i + 1

                absorbed = 0

                while j < len(entities):

                    nxt = entities[j]

                    nxt_text = (
                        nxt.text or ""
                    ).strip()

                    if not nxt_text:

                        break

                    # absorb names / ids / dates

                    if (

                        NAME_PATTERN.match(
                            nxt_text
                        )

                        or DATE_PATTERN.search(
                            nxt_text
                        )

                        or IDENTIFIER_PATTERN.search(
                            nxt_text
                        )

                        or nxt_text.isalpha()
                    ):

                        merged_text += (
                            " " + nxt_text
                        )

                        merged_bbox = (

                            self._merge_bbox(

                                merged_bbox,

                                nxt.bbox,
                            )
                        )

                        absorbed += 1

                        j += 1

                    else:

                        break

                expanded.append(

                    PHIEntity(

                        text=merged_text,

                        label="CONTEXT_PHI",

                        confidence=0.95,

                        source=PHISource.RULE,

                        bbox=merged_bbox,
                    )
                )

                i = j

                continue

            expanded.append(
                current
            )

            i += 1

        return expanded

    # =======================================================
    # CLASSIFIER
    # =======================================================

    def _classify(
        self,
        entity: PHIEntity,
    ) -> PHIEntity | None:

        text = str(

            entity.text
            or entity.metadata_value
            or ""

        ).strip()

        if not text:

            return None

        upper = (

            text.upper()

            .replace(":", "")

            .replace("-", "")

            .strip()
        )

        # --------------------------------------
        # KEYWORDS
        # --------------------------------------

        for keyword in KEYWORDS:

            if keyword in upper:

                entity.label = keyword

                entity.confidence = max(

                    entity.confidence,

                    0.95,
                )

                entity.source = PHISource.RULE

                return entity

        # --------------------------------------
        # DATE
        # --------------------------------------

        if DATE_PATTERN.search(
            text
        ):

            entity.label = "DATE"

            entity.confidence = 0.90

            entity.source = PHISource.RULE

            return entity

        # --------------------------------------
        # MRN
        # --------------------------------------

        if IDENTIFIER_PATTERN.search(
            text
        ):

            entity.label = "IDENTIFIER"

            entity.confidence = 0.90

            entity.source = PHISource.RULE

            return entity

        # --------------------------------------
        # UID
        # --------------------------------------

        if UID_PATTERN.match(
            text
        ):

            entity.label = "UID"

            entity.confidence = 0.95

            entity.source = PHISource.RULE

            return entity

        # --------------------------------------
        # AGE
        # --------------------------------------

        if AGE_PATTERN.search(
            text
        ):

            entity.label = "AGE"

            entity.confidence = 0.80

            entity.source = PHISource.RULE

            return entity

        # --------------------------------------
        # PERSON NAME
        # --------------------------------------

        if NAME_PATTERN.match(
            text
        ):

            entity.label = "PERSON_NAME"

            entity.confidence = 0.85

            entity.source = PHISource.RULE

            return entity

        return None

    # =======================================================
    # BBOX MERGE
    # =======================================================

    def _merge_bbox(
        self,
        a: BoundingBox | None,
        b: BoundingBox | None,
    ) -> BoundingBox | None:

        if a is None:

            return b

        if b is None:

            return a

        return BoundingBox(

            x1=min(
                a.x1,
                b.x1,
            ),

            y1=min(
                a.y1,
                b.y1,
            ),

            x2=max(
                a.x2,
                b.x2,
            ),

            y2=max(
                a.y2,
                b.y2,
            ),
        )