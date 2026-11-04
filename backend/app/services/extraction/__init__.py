from __future__ import annotations

from app.config import Settings, get_settings
from app.services.extraction.base import Extractor


def get_extractor(settings: Settings | None = None, kind: str | None = None) -> Extractor:
    settings = settings or get_settings()
    kind = kind or settings.resolved_extractor()
    if kind == "claude":
        from app.services.extraction.claude import ClaudeExtractor

        return ClaudeExtractor(settings)
    if kind == "heuristic":
        from app.services.extraction.heuristic import HeuristicExtractor

        return HeuristicExtractor()
    raise ValueError(f"Unknown extractor: {kind}")


__all__ = ["Extractor", "get_extractor"]
