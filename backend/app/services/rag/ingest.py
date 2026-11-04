"""Load policy documents into PostgreSQL / pgvector."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Policy, PolicyChunk
from app.services.embeddings import embed_documents
from app.services.rag.chunking import chunk_policy
from app.services.text_extraction import extract_text

log = logging.getLogger(__name__)


def ingest_policy(session: Session, path: Path) -> Policy:
    """Parse, chunk and embed one policy PDF. Re-ingesting a policy replaces its chunks."""
    parsed = chunk_policy(extract_text(path).text)
    vectors = embed_documents([c.embedding_text for c in parsed.chunks])

    policy = session.scalar(select(Policy).where(Policy.policy_number == parsed.policy_number))
    if policy is None:
        policy = Policy(policy_number=parsed.policy_number, title=parsed.title, source_filename=path.name)
        session.add(policy)
    else:
        policy.title, policy.source_filename = parsed.title, path.name
        policy.chunks.clear()
        session.flush()

    for chunk, vector in zip(parsed.chunks, vectors, strict=True):
        policy.chunks.append(
            PolicyChunk(
                chunk_index=chunk.index,
                section=chunk.section,
                group_name=chunk.group,
                content=chunk.content,
                embedding=vector.tolist(),
            )
        )
    session.flush()
    log.info("Ingested %s (%d chunks)", parsed.policy_number, len(parsed.chunks))
    return policy
