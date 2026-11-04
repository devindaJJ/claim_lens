from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db import get_session
from app.models import ClaimRecord, ClaimStatus
from app.schemas.api import ClaimDetail, ClaimList, ClaimSummary, DecisionIn, FieldReviewIn, StatsOut
from app.services import claims as claim_service

router = APIRouter(prefix="/api/claims", tags=["claims"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _load(session: Session, claim_id: uuid.UUID) -> ClaimRecord:
    record = session.scalar(
        select(ClaimRecord)
        .where(ClaimRecord.id == claim_id)
        .options(selectinload(ClaimRecord.fields), selectinload(ClaimRecord.rules))
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    return record


def enqueue(claim_id: uuid.UUID) -> None:
    from app.worker import process_claim

    process_claim.delay(str(claim_id))


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ClaimSummary)
async def upload_claim(session: SessionDep, settings: SettingsDep, file: Annotated[UploadFile, File()]) -> ClaimSummary:
    """Upload a claim packet (PDF). Processing happens asynchronously."""
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {settings.max_upload_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are accepted")

    record = claim_service.create_claim(session, settings, file.filename or "claim.pdf", data)
    session.commit()
    enqueue(record.id)
    return ClaimSummary.from_record(record)


@router.get("", response_model=ClaimList)
def list_claims(
    session: SessionDep,
    status_filter: Annotated[list[ClaimStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClaimList:
    stmt = select(ClaimRecord)
    count_stmt = select(func.count(ClaimRecord.id))
    if status_filter:
        stmt = stmt.where(ClaimRecord.status.in_(status_filter))
        count_stmt = count_stmt.where(ClaimRecord.status.in_(status_filter))
    records = session.scalars(
        stmt.options(selectinload(ClaimRecord.fields), selectinload(ClaimRecord.rules))
        .order_by(ClaimRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ClaimList(items=[ClaimSummary.from_record(r) for r in records], total=session.scalar(count_stmt) or 0)


@router.get("/stats", response_model=StatsOut)
def claim_stats(session: SessionDep) -> StatsOut:
    rows = session.execute(select(ClaimRecord.status, func.count()).group_by(ClaimRecord.status)).all()
    counts = {s.value: 0 for s in ClaimStatus} | {s.value: n for s, n in rows}
    return StatsOut(counts=counts, total=sum(counts.values()))


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(session: SessionDep, claim_id: uuid.UUID) -> ClaimDetail:
    return ClaimDetail.from_record(_load(session, claim_id))


@router.get("/{claim_id}/document", response_class=FileResponse)
def get_document(session: SessionDep, claim_id: uuid.UUID) -> FileResponse:
    record = _load(session, claim_id)
    return FileResponse(
        record.storage_path,
        media_type="application/pdf",
        filename=record.filename,
        content_disposition_type="inline",
    )


@router.patch("/{claim_id}/fields/{name}", response_model=ClaimDetail)
def review_field(
    session: SessionDep, settings: SettingsDep, claim_id: uuid.UUID, name: str, body: FieldReviewIn
) -> ClaimDetail:
    """Accept an extracted value, or correct it. Corrections re-run the policy rules."""
    record = _load(session, claim_id)
    try:
        claim_service.review_field(session, settings, record, name, body.action, body.value)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except claim_service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    session.commit()
    return ClaimDetail.from_record(record)


@router.post("/{claim_id}/decision", response_model=ClaimDetail)
def decide_claim(session: SessionDep, claim_id: uuid.UUID, body: DecisionIn) -> ClaimDetail:
    record = _load(session, claim_id)
    try:
        claim_service.decide(record, body.decision, body.notes)
    except claim_service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.commit()
    return ClaimDetail.from_record(record)


@router.post("/{claim_id}/reprocess", status_code=status.HTTP_202_ACCEPTED, response_model=ClaimSummary)
def reprocess_claim(session: SessionDep, claim_id: uuid.UUID) -> ClaimSummary:
    """Run extraction again, discarding any review progress (e.g. after a failure)."""
    record = _load(session, claim_id)
    if record.status in claim_service.FINAL_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Claim is already {record.status.value}")
    record.status, record.error = ClaimStatus.QUEUED, None
    session.commit()
    enqueue(record.id)
    return ClaimSummary.from_record(record)
