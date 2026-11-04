from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

EMBEDDING_DIM = 384


def _now() -> datetime:
    return datetime.now(UTC)


class ClaimStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class FieldStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"


def _enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e], native_enum=False, length=32)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    source_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chunks: Mapped[list[PolicyChunk]] = relationship(
        back_populates="policy", cascade="all, delete-orphan", order_by="PolicyChunk.chunk_index"
    )


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"
    __table_args__ = (UniqueConstraint("policy_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(200))
    group_name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    policy: Mapped[Policy] = relationship(back_populates="chunks")


class ClaimRecord(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[ClaimStatus] = mapped_column(
        _enum(ClaimStatus, "claim_status"), default=ClaimStatus.QUEUED, index=True
    )
    extractor: Mapped[str | None] = mapped_column(String(32))
    text_method: Mapped[str | None] = mapped_column(String(16))
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    page_count: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    decision_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fields: Mapped[list[ClaimField]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="ClaimField.position"
    )
    rules: Mapped[list[RuleOutcome]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="RuleOutcome.position"
    )


class ClaimField(Base):
    __tablename__ = "claim_fields"
    __table_args__ = (UniqueConstraint("claim_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    extracted_value: Mapped[str | None] = mapped_column(Text)
    corrected_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FieldStatus] = mapped_column(_enum(FieldStatus, "field_status"), default=FieldStatus.PENDING)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    claim: Mapped[ClaimRecord] = relationship(back_populates="fields")

    @property
    def value(self) -> str | None:
        return self.corrected_value if self.status == FieldStatus.CORRECTED else self.extracted_value


class RuleOutcome(Base):
    __tablename__ = "rule_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    claim: Mapped[ClaimRecord] = relationship(back_populates="rules")
