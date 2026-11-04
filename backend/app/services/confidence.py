"""Field confidence calibration.

The raw confidence reported by an extractor is adjusted by two independent signals:

* **Grounding** – the evidence quoted for a value must appear in the document text. An
  ungrounded value is capped, since it may be hallucinated or inferred.
* **OCR quality** – values read from scanned pages inherit some of Tesseract's uncertainty.
"""

from __future__ import annotations

from app.schemas.domain import DocumentText, FieldMeta
from app.services.normalize import text_contains

UNGROUNDED_CAP = 0.5


def calibrate(
    value: object | None,
    raw_confidence: float,
    evidence: str | None,
    document: DocumentText,
) -> FieldMeta:
    if value is None:
        return FieldMeta(confidence=0.0, evidence=evidence, grounded=False)

    confidence = min(max(raw_confidence, 0.0), 1.0)
    grounded = bool(evidence) and text_contains(document.text, evidence or "")
    if not grounded:
        confidence = min(confidence, UNGROUNDED_CAP)

    ocr = document.ocr_confidence
    if ocr is not None:
        confidence *= 0.6 + 0.4 * ocr

    return FieldMeta(confidence=round(confidence, 3), evidence=evidence, grounded=grounded)
