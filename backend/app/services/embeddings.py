"""Local sentence embeddings (fastembed / ONNX) for policy retrieval.

Runs on CPU with no external service. The model (~130 MB) downloads on first use.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from functools import lru_cache

import numpy as np

from app.config import get_settings

_lock = threading.Lock()


@lru_cache
def _model():
    from fastembed import TextEmbedding

    settings = get_settings()
    cache = str(settings.embedding_cache_dir) if settings.embedding_cache_dir else None
    return TextEmbedding(model_name=settings.embedding_model, cache_dir=cache)


def embed_documents(texts: Sequence[str]) -> np.ndarray:
    with _lock:
        vectors = list(_model().passage_embed(list(texts)))
    return _normalise(np.asarray(vectors, dtype=np.float32))


def embed_query(text: str) -> np.ndarray:
    with _lock:
        vector = next(iter(_model().query_embed(text)))
    return _normalise(np.asarray(vector, dtype=np.float32)[None, :])[0]


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.clip(norms, 1e-12, None)
