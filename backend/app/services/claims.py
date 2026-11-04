"""Persistence and review workflow for claims."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ClaimField, ClaimRecord, ClaimStatus, FieldStatus, RuleOutcome
from app.schemas.domain import CLAIM_FIELDS, Claim, ClaimType, FieldMeta, ProcessingResult, Route, RuleResult
from app.services.pipeline import Pipeline, route_claim
from app.services.rag.retriever import PgVectorRetriever

FINAL_STATUSES = {ClaimStatus.APPROVED, ClaimStatus.REJECTED}


class WorkflowError(ValueError):
    """An action that is not allowed in the claim's current state."""


# --- value (de)serialisation ------------------------------------------------------------


def serialize_value(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, ClaimType):
        return value.value
    return str(value)


def parse_field_value(name: str, raw: str | None) -> object | None:
    """Validate a reviewer-supplied value. Raises ``ValueError`` with a readable message."""
    if raw is None or not raw.strip():
        return None
    raw = raw.strip()
    if name == "incident_date":
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Incident date must be in YYYY-MM-DD format") from exc
    if name == "amount":
        try:
            amount = round(float(raw.replace(",", "").lstrip("$")), 2)
        except ValueError as exc:
            raise ValueError("Amount must be a number") from exc
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        return amount
    if name == "claim_type":
        try:
            return ClaimType(raw)
        except ValueError as exc:
            raise ValueError(f"Unknown claim type: {raw}") from exc
    if name == "policy_number":
        return raw.upper()
    return raw


def claim_from_record(record: ClaimRecord) -> Claim:
    values = {f.name: parse_field_value(f.name, f.value) for f in record.fields}
    return Claim(**values, description=record.description)


def field_meta_for_routing(record: ClaimRecord) -> dict[str, FieldMeta]:
    """Reviewed fields count as fully confident; pending fields keep their model confidence."""
    return {
        f.name: FieldMeta(
            confidence=1.0 if f.status != FieldStatus.PENDING else f.confidence,
            evidence=f.evidence,
            grounded=f.grounded,
        )
        for f in record.fields
    }


# --- writes ---------------------------------------------------------------------------


def create_claim(session: Session, settings: Settings, filename: str, data: bytes) -> ClaimRecord:
    claim_id = uuid.uuid4()
    directory = settings.storage_dir / "claims"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{claim_id}.pdf"
    path.write_bytes(data)
    record = ClaimRecord(
        id=claim_id, filename=Path(filename).name, storage_path=str(path), status=ClaimStatus.QUEUED, review_reasons=[]
    )
    session.add(record)
    session.flush()
    return record


def _replace_rules(record: ClaimRecord, rules: list[RuleResult]) -> None:
    record.rules.clear()
    for position, rule in enumerate(rules):
        record.rules.append(
            RuleOutcome(
                position=position,
                code=rule.code.value,
                passed=rule.passed,
                message=rule.message,
                evidence=[e.model_dump(exclude={"content"}) | {"excerpt": e.content[:400]} for e in rule.evidence],
            )
        )


def save_result(record: ClaimRecord, result: ProcessingResult) -> None:
    claim, metas = result.extraction.claim, result.extraction.fields
    record.extractor = result.extraction.extractor
    record.text_method = result.document.method
    record.ocr_confidence = result.document.ocr_confidence
    record.page_count = len(result.document.pages)
    record.raw_text = result.document.text
    record.description = claim.description
    record.fields.clear()
    for position, name in enumerate(CLAIM_FIELDS):
        meta = metas[name]
        record.fields.append(
            ClaimField(
                position=position,
                name=name,
                extracted_value=serialize_value(getattr(claim, name)),
                confidence=meta.confidence,
                grounded=meta.grounded,
                evidence=meta.evidence,
                status=FieldStatus.PENDING,
            )
        )
    _replace_rules(record, result.rules)
    record.review_reasons = result.routing.reasons
    record.status = (
        ClaimStatus.AUTO_APPROVED if result.routing.route == Route.AUTO_APPROVED else ClaimStatus.NEEDS_REVIEW
    )
    record.processed_at = datetime.now(UTC)
    record.error = None


def revalidate(session: Session, settings: Settings, record: ClaimRecord) -> None:
    pipeline = Pipeline.create(settings, PgVectorRetriever(session))
    rules = pipeline.validate(claim_from_record(record))
    _replace_rules(record, rules)
    record.review_reasons = route_claim(field_meta_for_routing(record), rules, settings.confidence_threshold).reasons


def review_field(
    session: Session,
    settings: Settings,
    record: ClaimRecord,
    name: str,
    action: str,
    value: str | None = None,
) -> ClaimRecord:
    if record.status in FINAL_STATUSES or record.status in {ClaimStatus.QUEUED, ClaimStatus.PROCESSING}:
        raise WorkflowError(f"Fields cannot be reviewed while the claim is {record.status.value}")
    field = next((f for f in record.fields if f.name == name), None)
    if field is None:
        raise LookupError(f"Unknown field: {name}")

    previous_value = field.value
    if action == "accept":
        field.status, field.corrected_value = FieldStatus.ACCEPTED, None
    elif action == "correct":
        field.corrected_value = serialize_value(parse_field_value(name, value))
        field.status = FieldStatus.CORRECTED
    else:
        raise WorkflowError(f"Unknown action: {action}")
    field.reviewed_at = datetime.now(UTC)

    if field.value != previous_value:
        revalidate(session, settings, record)
    else:
        record.review_reasons = route_claim(
            field_meta_for_routing(record),
            [RuleResult(code=r.code, passed=r.passed, message=r.message) for r in record.rules],
            settings.confidence_threshold,
        ).reasons
    record.updated_at = datetime.now(UTC)
    return record


def decide(record: ClaimRecord, decision: str, notes: str | None) -> ClaimRecord:
    if record.status in FINAL_STATUSES:
        raise WorkflowError(f"Claim is already {record.status.value}")
    if record.status not in {ClaimStatus.NEEDS_REVIEW, ClaimStatus.AUTO_APPROVED}:
        raise WorkflowError(f"Claim cannot be decided while {record.status.value}")
    if decision == "approve":
        pending = [f.name for f in record.fields if f.status == FieldStatus.PENDING]
        if pending:
            raise WorkflowError("Review every field before approving: " + ", ".join(pending))
        record.status = ClaimStatus.APPROVED
    elif decision == "reject":
        record.status = ClaimStatus.REJECTED
    else:
        raise WorkflowError(f"Unknown decision: {decision}")
    record.decision_notes = notes
    record.decided_at = datetime.now(UTC)
    return record
