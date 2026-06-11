from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Auth ─────────────────────────────────────────────────────────────────
    api_key: str = "dev-secret-change-me"

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "development"
    app_version: str = "1.0.0"
    log_level: str = "info"

    # ── File Limits ───────────────────────────────────────────────────────────
    max_files: int = 10
    max_file_size_mb: int = 25
    max_total_size_mb: int = 100
    max_page_limit: int = 200

    # ── Storage (local) ───────────────────────────────────────────────────────
    upload_dir: str = "uploads"

    # ── Webhook ───────────────────────────────────────────────────────────────
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3
    webhook_signing_secret: str | None = None

    # ── VertexAI Embedding ────────────────────────────────────────────────────
    vertex_project_id: str = "proj-dpi-shared"  # auto-detected from SA
    vertex_location: str = "us-central1"
    vertex_embedding_model: str = "publishers/google/models/gemini-embedding-001"
    vertex_credentials_json: str = "gcp-service-account.json"

    # ── VectorDB (FAISS HNSW) ─────────────────────────────────────────────────
    vector_store_dir: str = "vector_store"
    rulebook_clinical_dir: str = "rulebook_clinical"
    rulebook_insurance_dir: str = "rulebook_insurance"
    vector_embedding_dim: int = 3072     # gemini-embedding-001 full dimension
    vector_hnsw_m: int = 32             # HNSW neighbors per node
    vector_hnsw_ef_construction: int = 200  # build-time graph quality
    vector_hnsw_ef_search: int = 50     # query-time recall vs speed

    # ── LLM Inference (Vertex AI MaaS) ────────────────────────────────────────
    llm_project_id: str = "proj-dpi-shared"
    llm_location: str = "us-central1"
    llm_model: str = "publishers/google/models/gemma-4-26b-a4b-it-maas"
    llm_credentials_json: str = "gcp-service-account.json"

    # ── Queueing / Background Jobs ────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_total_size_bytes(self) -> int:
        return self.max_total_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
