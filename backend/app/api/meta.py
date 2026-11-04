from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Policy, PolicyChunk
from app.schemas.api import ClaimTypeOut, PolicyOut
from app.schemas.domain import CLAIM_TYPE_LABELS

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health(
    session: Annotated[Session, Depends(get_session)], settings: Annotated[Settings, Depends(get_settings)]
) -> dict:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "extractor": settings.resolved_extractor(), "model": settings.anthropic_model}


@router.get("/policies", response_model=list[PolicyOut])
def list_policies(session: Annotated[Session, Depends(get_session)]) -> list[PolicyOut]:
    rows = session.execute(
        select(Policy, func.count(PolicyChunk.id))
        .outerjoin(PolicyChunk)
        .group_by(Policy.id)
        .order_by(Policy.policy_number)
    ).all()
    return [
        PolicyOut(policy_number=p.policy_number, title=p.title, source_filename=p.source_filename, chunks=n)
        for p, n in rows
    ]


@router.get("/claim-types", response_model=list[ClaimTypeOut])
def claim_types() -> list[ClaimTypeOut]:
    return [ClaimTypeOut(value=t.value, label=label) for t, label in CLAIM_TYPE_LABELS.items()]
