from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", REPO_ROOT / ".env"), extra="ignore")

    # Infrastructure
    database_url: str = "postgresql+psycopg://claimlens:claimlens@localhost:5432/claimlens"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = REPO_ROOT / "storage"
    data_dir: Path = REPO_ROOT / "data"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    max_upload_mb: int = 20

    # Extraction. "auto" uses Claude when credentials are configured, otherwise the
    # deterministic regex baseline.
    extractor: Literal["auto", "claude", "heuristic"] = "auto"
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_max_tokens: int = 16000
    attach_pdf_to_llm: bool = False

    # OCR
    ocr_min_chars_per_page: int = 40
    ocr_dpi: int = 300
    tesseract_lang: str = "eng"

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_cache_dir: Path | None = None
    retrieval_top_k: int = 3

    # Routing
    confidence_threshold: float = Field(default=0.80, ge=0, le=1)

    def resolved_extractor(self) -> Literal["claude", "heuristic"]:
        if self.extractor != "auto":
            return self.extractor
        has_credentials = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
        return "claude" if has_credentials else "heuristic"


@lru_cache
def get_settings() -> Settings:
    return Settings()
