"""The claim processing pipeline: text → fields → policy rules → routing.

The pipeline itself has no database dependency; persistence lives in the worker. This keeps
it usable from the evaluation harness and unit tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.schemas.domain import (
    CLAIM_FIELDS,
    Claim,
    FieldMeta,
    ProcessingResult,
    Route,
    RoutingDecision,
    RuleCode,
    RuleResult,
)
from app.services.extraction import Extractor, get_extractor
from app.services.interpretation import Interpreter, get_interpreter
from app.services.rag.retriever import Retriever, retrieve_for_claim
from app.services.text_extraction import extract_text
from app.services.validation import check_required_fields, evaluate_rules

log = logging.getLogger(__name__)


def route_claim(fields: dict[str, FieldMeta], rules: list[RuleResult], threshold: float) -> RoutingDecision:
    reasons: list[str] = []
    for name in CLAIM_FIELDS:
        meta = fields.get(name)
        if meta is not None and meta.confidence < threshold:
            reasons.append(f"Low confidence on {name.replace('_', ' ')} ({meta.confidence:.2f})")
    reasons.extend(f"Rule failed: {r.message}" for r in rules if not r.passed)
    return RoutingDecision(route=Route.NEEDS_REVIEW if reasons else Route.AUTO_APPROVED, reasons=reasons)


@dataclass
class Pipeline:
    settings: Settings
    retriever: Retriever
    extractor: Extractor
    interpreter: Interpreter

    @classmethod
    def create(cls, settings: Settings, retriever: Retriever, kind: str | None = None) -> Pipeline:
        return cls(
            settings=settings,
            retriever=retriever,
            extractor=get_extractor(settings, kind),
            interpreter=get_interpreter(settings, kind),
        )

    def run(self, pdf_path: Path) -> ProcessingResult:
        document = extract_text(pdf_path, self.settings)
        extraction = self.extractor.extract(document, pdf_path)
        rules = self.validate(extraction.claim)
        routing = route_claim(extraction.fields, rules, self.settings.confidence_threshold)
        log.info("Processed %s: route=%s (%d reasons)", pdf_path.name, routing.route, len(routing.reasons))
        return ProcessingResult(document=document, extraction=extraction, rules=rules, routing=routing)

    def validate(self, claim: Claim) -> list[RuleResult]:
        results = [check_required_fields(claim)]
        if not claim.policy_number:
            return results
        if not self.retriever.has_policy(claim.policy_number):
            results.append(
                RuleResult(
                    code=RuleCode.POLICY_FOUND,
                    passed=False,
                    message=f"No policy with number {claim.policy_number} is on file.",
                )
            )
            return results
        results.append(
            RuleResult(code=RuleCode.POLICY_FOUND, passed=True, message=f"Policy {claim.policy_number} found.")
        )
        chunks = retrieve_for_claim(self.retriever, claim, self.settings.retrieval_top_k)
        terms = self.interpreter.interpret(claim, chunks)
        results.extend(evaluate_rules(claim, terms, chunks))
        return results
