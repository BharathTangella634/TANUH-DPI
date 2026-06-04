"""Pydantic schemas for the Privacy Filter API contract.

These mirror the original privacy_filter service so the frontend, session
logger, and external API consumers continue to work unchanged. The backing
engine is now MedDeID (medical-image / DICOM / document de-identification).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """A single detected PII / PHI span.

    For burned-in pixel text and metadata tags there is no character offset,
    so ``start``/``end`` are optional. ``word`` carries the detected value
    (text content) when available; for pixel regions it may be ``None``.
    """
    entity_group: str = Field(..., description="PHI label (e.g. PERSON_NAME, DATE, PatientName)")
    score: float = Field(..., description="Detection confidence 0..1")
    word: Optional[str] = Field(None, description="Detected text/value, if readable")
    start: Optional[int] = None
    end: Optional[int] = None
    bbox: Optional[dict] = Field(None, description="Bounding box {x1, y1, x2, y2, page} for pixel regions")


class RedactionResult(BaseModel):
    job_id: str
    filename: str
    content_type: str
    entities: List[Entity]
    entity_counts: dict[str, int]
    original_url: str
    redacted_url: str
    text_preview_original: Optional[str] = None
    text_preview_redacted: Optional[str] = None
    notes: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    model: str
    device: str
    model_loaded: bool
