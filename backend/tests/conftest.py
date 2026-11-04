from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.schemas.domain import DocumentText, PageText

DATA_DIR = get_settings().data_dir


def doc(text: str, method: str = "pdf_text", ocr: float | None = None) -> DocumentText:
    return DocumentText(pages=[PageText(page=1, text=text, method=method, ocr_confidence=ocr)])


@pytest.fixture(scope="session")
def data_dir() -> Path:
    if not (DATA_DIR / "ground_truth").exists():
        pytest.skip("Synthetic dataset not generated (run scripts/generate_data.py)")
    return DATA_DIR


@pytest.fixture(scope="session")
def retriever(data_dir: Path):
    from app.services.rag.retriever import InMemoryRetriever

    return InMemoryRetriever.from_directory(data_dir / "policies")
