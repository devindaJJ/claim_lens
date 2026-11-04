"""Request and response models for the HTTP API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClaimRecord, ClaimStatus, FieldStatus


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    value: str | None
    extracted_value: str | None
    corrected_value: str | None
    confidence: float
    grounded: bool
    evidence: str | None
    status: FieldStatus
    reviewed_at: datetime | None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    passed: bool
    message: str
    evidence: list[dict[str, Any]]


class ClaimSummary(BaseModel):
    id: uuid.UUID
    filename: str
    status: ClaimStatus
    policy_number: str | None
    claimant_name: str | None
    amount: str | None
    claim_type: str | None
    min_confidence: float | None
    failed_rules: int
    review_reasons: list[str]
    created_at: datetime
    processed_at: datetime | None

    @classmethod
    def from_record(cls, record: ClaimRecord) -> ClaimSummary:
        values = {f.name: f.value for f in record.fields}
        return cls(
            id=record.id,
            filename=record.filename,
            status=record.status,
            policy_number=values.get("policy_number"),
            claimant_name=values.get("claimant_name"),
            amount=values.get("amount"),
            claim_type=values.get("claim_type"),
            min_confidence=min((f.confidence for f in record.fields), default=None),
            failed_rules=sum(not r.passed for r in record.rules),
            review_reasons=record.review_reasons or [],
            created_at=record.created_at,
            processed_at=record.processed_at,
        )


class ClaimDetail(ClaimSummary):
    extractor: str | None
    text_method: str | None
    ocr_confidence: float | None
    page_count: int | None
    description: str | None
    error: str | None
    decision_notes: str | None
    decided_at: datetime | None
    fields: list[FieldOut]
    rules: list[RuleOut]

    @classmethod
    def from_record(cls, record: ClaimRecord) -> ClaimDetail:
        summary = ClaimSummary.from_record(record).model_dump()
        return cls(
            **summary,
            extractor=record.extractor,
            text_method=record.text_method,
            ocr_confidence=record.ocr_confidence,
            page_count=record.page_count,
            description=record.description,
            error=record.error,
            decision_notes=record.decision_notes,
            decided_at=record.decided_at,
            fields=[FieldOut.model_validate(f) for f in record.fields],
            rules=[RuleOut.model_validate(r) for r in record.rules],
        )


class ClaimList(BaseModel):
    items: list[ClaimSummary]
    total: int


class FieldReviewIn(BaseModel):
    action: Literal["accept", "correct"]
    value: str | None = Field(default=None, max_length=500)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str | None = Field(default=None, max_length=2000)


class StatsOut(BaseModel):
    counts: dict[str, int]
    total: int


class PolicyOut(BaseModel):
    policy_number: str
    title: str
    source_filename: str
    chunks: int


class ClaimTypeOut(BaseModel):
    value: str
    label: str
