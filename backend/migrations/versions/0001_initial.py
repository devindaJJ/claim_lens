"""Initial schema: policies, policy chunks (pgvector), claims, fields and rule outcomes.

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "policies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_number", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_policies_policy_number", "policies", ["policy_number"], unique=True)

    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_id", sa.Integer, sa.ForeignKey("policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("section", sa.String(200), nullable=False),
        sa.Column("group_name", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.UniqueConstraint("policy_id", "chunk_index"),
    )
    op.create_index("ix_policy_chunks_policy_id", "policy_chunks", ["policy_id"])
    op.execute("CREATE INDEX ix_policy_chunks_embedding ON policy_chunks USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("extractor", sa.String(32)),
        sa.Column("text_method", sa.String(16)),
        sa.Column("ocr_confidence", sa.Float),
        sa.Column("page_count", sa.Integer),
        sa.Column("raw_text", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("review_reasons", sa.JSON, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("decision_notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_created_at", "claims", ["created_at"])

    op.create_table(
        "claim_fields",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("claim_id", sa.Uuid, sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("extracted_value", sa.Text),
        sa.Column("corrected_value", sa.Text),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("grounded", sa.Boolean, nullable=False),
        sa.Column("evidence", sa.Text),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("claim_id", "name"),
    )
    op.create_index("ix_claim_fields_claim_id", "claim_fields", ["claim_id"])

    op.create_table(
        "rule_outcomes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("claim_id", sa.Uuid, sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
    )
    op.create_index("ix_rule_outcomes_claim_id", "rule_outcomes", ["claim_id"])


def downgrade() -> None:
    op.drop_table("rule_outcomes")
    op.drop_table("claim_fields")
    op.drop_table("claims")
    op.drop_table("policy_chunks")
    op.drop_table("policies")
