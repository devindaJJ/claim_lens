from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.schemas.domain import DocumentText, ExtractionResult


class Extractor(Protocol):
    """Turns a claim document into a structured :class:`~app.schemas.domain.Claim`."""

    name: str

    def extract(self, document: DocumentText, pdf_path: Path | None = None) -> ExtractionResult: ...
