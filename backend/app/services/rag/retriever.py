"""Policy clause retrieval.

``Retriever`` is implemented by :class:`PgVectorRetriever` (PostgreSQL + pgvector, used by
the API and worker) and :class:`InMemoryRetriever` (numpy, used by the evaluation harness
and tests). Both embed the same chunks with the same model, so results match.

Each claim asks three questions of its policy. Every question is a semantic search
restricted, via chunk metadata, to the policy section that can answer it, so a long or noisy
incident description cannot crowd the relevant exclusion clauses out of the results.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.domain import CLAIM_TYPE_LABELS, Claim, PolicyChunkRef
from app.services.embeddings import embed_documents, embed_query
from app.services.rag.chunking import ParsedPolicy, chunk_policy

MAX_QUERY_CHARS = 400


@dataclass(frozen=True)
class Query:
    text: str
    group: str | None  # case-insensitive substring of the section heading to search within


class Retriever(Protocol):
    def has_policy(self, policy_number: str) -> bool: ...

    def search(self, policy_number: str, query: str, k: int, group: str | None = None) -> list[PolicyChunkRef]: ...


def claim_queries(claim: Claim) -> list[Query]:
    """The questions the policy must answer for this claim."""
    queries = [Query("Policy number, policyholder, named insureds and policy period dates", "declarations")]
    if claim.claim_type:
        label = CLAIM_TYPE_LABELS[claim.claim_type]
        queries.append(
            Query(f"{label} coverage, claim type code {claim.claim_type.value}, limit and deductible", "coverages")
        )
    description = (claim.description or "")[:MAX_QUERY_CHARS]
    queries.append(Query(f"Excluded cause of loss: {description}", "exclusions"))
    return queries


def retrieve_for_claim(retriever: Retriever, claim: Claim, k: int) -> list[PolicyChunkRef]:
    """Union of the top-k chunks for each claim query, best score first."""
    if not claim.policy_number:
        return []
    best: dict[str, PolicyChunkRef] = {}
    for query in claim_queries(claim):
        for ref in retriever.search(claim.policy_number, query.text, k, query.group):
            current = best.get(ref.chunk_id)
            if current is None or (ref.score or 0) > (current.score or 0):
                best[ref.chunk_id] = ref
    return sorted(best.values(), key=lambda r: r.score or 0, reverse=True)


class InMemoryRetriever:
    def __init__(self, policies: Iterable[ParsedPolicy]) -> None:
        self._refs: dict[str, list[PolicyChunkRef]] = {}
        self._vectors: dict[str, np.ndarray] = {}
        for policy in policies:
            self._refs[policy.policy_number] = [
                PolicyChunkRef(
                    chunk_id=f"{policy.policy_number}#{c.index}",
                    policy_number=policy.policy_number,
                    section=c.section,
                    group=c.group,
                    content=c.content,
                )
                for c in policy.chunks
            ]
            self._vectors[policy.policy_number] = embed_documents([c.embedding_text for c in policy.chunks])

    @classmethod
    def from_directory(cls, directory: Path) -> InMemoryRetriever:
        from app.services.text_extraction import extract_text

        return cls(chunk_policy(extract_text(path).text) for path in sorted(directory.glob("*.pdf")))

    def has_policy(self, policy_number: str) -> bool:
        return policy_number in self._refs

    def search(self, policy_number: str, query: str, k: int, group: str | None = None) -> list[PolicyChunkRef]:
        refs = self._refs.get(policy_number, [])
        candidates = [i for i, r in enumerate(refs) if group is None or group.casefold() in r.group.casefold()]
        if not candidates:
            return []
        scores = self._vectors[policy_number][candidates] @ embed_query(query)
        order = np.argsort(-scores)[:k]
        return [refs[candidates[i]].model_copy(update={"score": round(float(scores[i]), 4)}) for i in order]


class PgVectorRetriever:
    def __init__(self, session: Session) -> None:
        self.session = session

    def has_policy(self, policy_number: str) -> bool:
        from app.models import Policy

        return self.session.scalar(select(Policy.id).where(Policy.policy_number == policy_number)) is not None

    def search(self, policy_number: str, query: str, k: int, group: str | None = None) -> list[PolicyChunkRef]:
        from app.models import Policy, PolicyChunk

        distance = PolicyChunk.embedding.cosine_distance(embed_query(query).tolist())
        stmt = (
            select(PolicyChunk, distance.label("distance"))
            .join(Policy)
            .where(Policy.policy_number == policy_number)
            .order_by(distance)
            .limit(k)
        )
        if group:
            stmt = stmt.where(PolicyChunk.group_name.ilike(f"%{group}%"))
        return [
            PolicyChunkRef(
                chunk_id=f"{policy_number}#{chunk.chunk_index}",
                policy_number=policy_number,
                section=chunk.section,
                group=chunk.group_name,
                content=chunk.content,
                score=round(1 - float(dist), 4),
            )
            for chunk, dist in self.session.execute(stmt).all()
        ]
