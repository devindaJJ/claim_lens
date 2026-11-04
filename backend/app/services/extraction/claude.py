"""Claude-backed extractor using structured outputs into a Pydantic schema."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings
from app.schemas.domain import CLAIM_TYPE_LABELS, Claim, ClaimType, DocumentText, ExtractionResult
from app.services.confidence import calibrate
from app.services.normalize import coerce_date, normalize_space


class _TextField(BaseModel):
    value: str | None = Field(description="The value, or null if the document does not state it.")
    confidence: float = Field(description="Your confidence from 0.0 to 1.0 that the value is correct.")
    evidence: str | None = Field(description="A short verbatim quote from the document that supports the value.")


class _AmountField(BaseModel):
    value: float | None = Field(description="Total amount claimed as a plain number, e.g. 4250.00.")
    confidence: float
    evidence: str | None


class _ClaimTypeField(BaseModel):
    value: ClaimType | None
    confidence: float
    evidence: str | None


class ClaimExtraction(BaseModel):
    """Schema the model fills in. Converted to the domain :class:`Claim` afterwards."""

    policy_number: _TextField
    claimant_name: _TextField = Field(description="Full name of the person making the claim.")
    incident_date: _TextField = Field(description="Date the incident or loss occurred, as YYYY-MM-DD.")
    amount: _AmountField
    claim_type: _ClaimTypeField
    incident_description: str | None = Field(description="One or two sentence summary of what happened.")


_TYPE_LINES = "\n".join(f"- {t.value}: {label}" for t, label in CLAIM_TYPE_LABELS.items())

SYSTEM_PROMPT = f"""You extract structured data from insurance claim documents (claim forms, \
letters and scanned paperwork) for a claims-processing system. A human reviewer checks any \
field you are unsure about, so accurate confidence matters as much as accurate values.

Field definitions:
- policy_number: the insurance policy identifier exactly as written (e.g. DM-AUTO-2025-001).
- claimant_name: the person making the claim, not the insurer or a third party.
- incident_date: when the incident or loss happened. Not the date the form was signed, the \
letter was written, or the claim was reported. Slash dates on these forms are day-first \
(DD/MM/YYYY). Return ISO format YYYY-MM-DD.
- amount: the total amount being claimed. Null if no amount is stated, even if an invoice \
is said to follow.
- claim_type: one of the codes below, chosen from the claim category and what happened.
{_TYPE_LINES}

Rules:
- Use only what the document says. If a field is missing or illegible, return null with \
confidence 0. Do not guess or infer missing values.
- evidence must be copied verbatim from the document text (a short phrase is enough).
- confidence: around 0.95 when the value is clearly labelled and unambiguous; 0.7-0.85 when \
it comes from narrative text or needs interpretation; below 0.6 when the text is garbled, \
ambiguous or contradictory.
- Documents may come from OCR and contain recognition errors; correct obvious OCR errors in \
values, but lower your confidence when you do."""


class ClaudeExtractor:
    name = "claude"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, document: DocumentText, pdf_path: Path | None = None) -> ExtractionResult:
        from app.services.llm import structured_call

        content: list[dict[str, Any]] = []
        if self.settings.attach_pdf_to_llm and pdf_path is not None:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(pdf_path.read_bytes()).decode(),
                    },
                }
            )
        source = {
            "pdf_text": "the PDF text layer",
            "ocr": "OCR of a scanned document",
            "mixed": "the PDF text layer and OCR",
        }
        content.append(
            {
                "type": "text",
                "text": (
                    f"Document text (from {source[document.method]}):\n"
                    f"<document>\n{document.text}\n</document>\n\n"
                    "Extract the claim fields."
                ),
            }
        )

        result = structured_call(self.settings, system=SYSTEM_PROMPT, content=content, schema=ClaimExtraction)
        return to_extraction_result(result, document)


def to_extraction_result(result: ClaimExtraction, document: DocumentText) -> ExtractionResult:
    policy = normalize_space(result.policy_number.value).upper() if result.policy_number.value else None
    claimant = normalize_space(result.claimant_name.value) if result.claimant_name.value else None
    incident = coerce_date(result.incident_date.value)
    amount = round(result.amount.value, 2) if result.amount.value is not None and result.amount.value >= 0 else None

    claim = Claim(
        policy_number=policy,
        claimant_name=claimant,
        incident_date=incident,
        amount=amount,
        claim_type=result.claim_type.value,
        description=result.incident_description,
    )
    raw = {
        "policy_number": (policy, result.policy_number),
        "claimant_name": (claimant, result.claimant_name),
        "incident_date": (incident, result.incident_date),
        "amount": (amount, result.amount),
        "claim_type": (claim.claim_type, result.claim_type),
    }
    fields = {
        name: calibrate(value, field.confidence, field.evidence, document) for name, (value, field) in raw.items()
    }
    return ExtractionResult(claim=claim, fields=fields, extractor="claude")
