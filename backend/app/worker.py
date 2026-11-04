"""Celery application and background tasks."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from celery import Celery, Task

from app.config import get_settings
from app.db import session_scope
from app.models import ClaimRecord, ClaimStatus
from app.services.claims import save_result
from app.services.llm import LLMTransientError
from app.services.pipeline import Pipeline
from app.services.rag.retriever import PgVectorRetriever

log = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("claimlens", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)

MAX_RETRIES = 4


@celery_app.task(bind=True, name="claims.process", max_retries=MAX_RETRIES)
def process_claim(self: Task, claim_id: str) -> str:
    """Extract, validate and route one uploaded claim."""
    with session_scope() as session:
        record = session.get(ClaimRecord, uuid.UUID(claim_id))
        if record is None:
            log.warning("Claim %s no longer exists", claim_id)
            return "missing"
        record.status = ClaimStatus.PROCESSING
        session.commit()

        try:
            pipeline = Pipeline.create(settings, PgVectorRetriever(session))
            result = pipeline.run(Path(record.storage_path))
        except LLMTransientError as exc:
            if self.request.retries < MAX_RETRIES:
                record.status = ClaimStatus.QUEUED
                session.commit()
                raise self.retry(exc=exc, countdown=min(2 ** (self.request.retries + 2), 60)) from exc
            record.status, record.error = ClaimStatus.FAILED, f"Model unavailable after retries: {exc}"
            return record.status.value
        except Exception as exc:
            log.exception("Processing failed for claim %s", claim_id)
            session.rollback()  # the failure may have left the transaction unusable
            record.status, record.error = ClaimStatus.FAILED, str(exc)
            return record.status.value

        save_result(record, result)
        return record.status.value
