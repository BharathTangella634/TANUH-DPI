"""Bridge between the FastAPI layer and the MedDeID de-identification engine.

The original privacy_filter service ran a text PII model. This service swaps
that for MedDeID — a medical-imaging / DICOM / document de-identification
engine — while preserving the exact same API contract (Entity list,
entity_counts, redacted file). The FastAPI layer in ``main.py`` never needs to
know which engine backs it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

# MedDeID engine lives at the privacy_filter package root (sibling of app/).
from ..pipeline.engine import MedDeIDEngine
from ..registry.loader_registry import LoaderRegistry

logger = logging.getLogger("privacy_filter.service")

# Output extension per input type. MedDeID preserves the input format, so the
# redacted output keeps the same suffix (DICOM stays DICOM, JPG stays JPG…).
_SUPPORTED_SUFFIXES = {
    ".dcm", ".dicom",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    ".nii",                   # uncompressed NIfTI (.nii.gz handled specially)
    ".pdf",
}


def supported_extensions() -> List[str]:
    """Extensions the MedDeID engine can de-identify."""
    return sorted(_SUPPORTED_SUFFIXES | {".nii.gz"})


def is_supported(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return True
    return Path(name).suffix.lower() in _SUPPORTED_SUFFIXES


def out_extension(filename: str) -> str:
    """Redacted output keeps the input extension (format-preserving)."""
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    return Path(filename).suffix.lower()


# ---------------------------------------------------------------------------
# Engine singleton — reused across requests (cheap; no heavy model to load).
# ---------------------------------------------------------------------------

class _EngineHolder:
    _engine: MedDeIDEngine | None = None

    @classmethod
    def get(cls, ocr_backend: str = "tesseract", redaction_method: str = "mask") -> MedDeIDEngine:
        if cls._engine is None:
            logger.info("Initialising MedDeIDEngine (backend=%s, method=%s)",
                        ocr_backend, redaction_method)
            cls._engine = MedDeIDEngine(
                ocr_backend=ocr_backend,
                redaction_method=redaction_method,
            )
        return cls._engine


def engine_ready() -> bool:
    """Lightweight readiness check (tesseract present, engine constructable)."""
    try:
        _EngineHolder.get()
        return True
    except Exception:
        logger.exception("MedDeID engine failed readiness check")
        return False


# ---------------------------------------------------------------------------
# PHIEntity → API Entity mapping
# ---------------------------------------------------------------------------

def _phi_to_entity(phi) -> Dict[str, Any]:
    """Map a MedDeID PHIEntity to the API Entity dict.

    Burned-in pixel regions have no char offsets; metadata tags carry the
    value in ``metadata_value``. ``word`` falls back through the available
    text fields, or the metadata key for opaque pixel regions.
    """
    word = getattr(phi, "text", None) or getattr(phi, "metadata_value", None)
    if not word:
        # Pixel text region with no readable content — surface the key/label.
        word = getattr(phi, "metadata_key", None)

    bbox = getattr(phi, "bbox", None)
    bbox_dict = None
    if bbox is not None:
        bbox_dict = {
            "x1": int(getattr(bbox, "x1", 0)),
            "y1": int(getattr(bbox, "y1", 0)),
            "x2": int(getattr(bbox, "x2", 0)),
            "y2": int(getattr(bbox, "y2", 0)),
            "page": int(getattr(bbox, "page", 0) or 0),
        }

    return {
        "entity_group": getattr(phi, "label", "PHI") or "PHI",
        "score": float(getattr(phi, "confidence", 1.0) or 1.0),
        "word": word,
        "start": None,
        "end": None,
        "bbox": bbox_dict,
    }


def run_deidentification(
    input_path: Path,
    output_path: Path,
    *,
    ocr_backend: str = "tesseract",
    redaction_method: str = "mask",
) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, Any]]:
    """Run the MedDeID pipeline on ``input_path`` → ``output_path``.

    Returns
    -------
    entities       : list of API Entity dicts (metadata PHI + pixel PHI)
    entity_counts  : {entity_group: count}
    meta           : {validation_passed, risk_score, notes, phi_count,
                      overlay_count}
    """
    engine = _EngineHolder.get(ocr_backend, redaction_method)
    result = engine.process(input_path, output_path)

    entities: List[Dict[str, Any]] = []
    seen = set()

    # PDF path returns API-shape entity dicts directly (already include bbox).
    pdf_entities = result.get("pdf_entities")
    if pdf_entities is not None:
        for ent in pdf_entities:
            bb = ent.get("bbox") or {}
            key = (ent["entity_group"], ent.get("word"),
                   (bb.get("x1"), bb.get("y1"), bb.get("x2"), bb.get("y2"), bb.get("page")))
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)
    else:
        # Image / DICOM / NIfTI path: map PHIEntity objects → API entities.
        metadata_phi = result.get("metadata_phi", []) or []
        pixel_phi = result.get("pixel_phi", []) or []
        for phi in list(metadata_phi) + list(pixel_phi):
            ent = _phi_to_entity(phi)
            bbox = getattr(phi, "bbox", None)
            key = (
                ent["entity_group"],
                ent["word"],
                (bbox.x1, bbox.y1, bbox.x2, bbox.y2) if bbox is not None else None,
            )
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)

    counts: Dict[str, int] = {}
    for e in entities:
        counts[e["entity_group"]] = counts.get(e["entity_group"], 0) + 1

    validation = result.get("validation")
    meta = {
        "validation_passed": bool(getattr(validation, "passed", False)),
        "risk_score": float(getattr(validation, "risk_score", 0.0)),
        "notes": getattr(validation, "notes", None),
        "phi_count": int(result.get("phi_count", 0)),
        "overlay_count": int(result.get("overlay_count", 0)),
    }

    return entities, counts, meta
