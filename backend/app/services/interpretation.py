"""Interpret retrieved policy clauses into structured :class:`PolicyTerms`.

The interpreter only *reads* the policy; the pass/fail decisions are made by deterministic
code in :mod:`app.services.validation`, so every outcome is explainable and testable.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.schemas.domain import CLAIM_TYPE_LABELS, Claim, ExclusionHit, PolicyChunkRef, PolicyTerms
from app.services.normalize import coerce_date, parse_amount

PERIOD_RE = re.compile(r"Policy\s+Period:\s*(?P<start>\S+)\s+(?:to|-|until)\s+(?P<end>[\d\-/]+)", re.I)
INSUREDS_RE = re.compile(r"Named\s+Insureds?:\s*(?P<v>.+?)(?=\s+Policy\s+Period|\s+Policyholder|$)", re.I)
LIMIT_RE = re.compile(r"Limit\s+of\s+liability\s+per\s+claim:\s*(?P<v>\$?[\d,]+(?:\.\d{2})?)", re.I)
DEDUCTIBLE_RE = re.compile(r"Deductible:\s*(?P<v>\$?[\d,]+(?:\.\d{2})?)", re.I)

# Generic words that would make keyword matching of exclusion headings too eager.
_GENERIC = {
    "conditions",
    "treatment",
    "procedures",
    "drivers",
    "driver",
    "travel",
    "government",
    "advisory",
    "activities",
}


class Interpreter(Protocol):
    name: str

    def interpret(self, claim: Claim, chunks: list[PolicyChunkRef]) -> PolicyTerms: ...


def is_exclusion_chunk(chunk: PolicyChunkRef) -> bool:
    return "exclusion" in chunk.group.casefold() and chunk.section != chunk.group


def _common_terms(policy_number: str, chunks: list[PolicyChunkRef]) -> dict:
    terms: dict = {"policy_number": policy_number}
    for chunk in chunks:
        if (m := PERIOD_RE.search(chunk.content)) and "period_start" not in terms:
            terms["period_start"] = coerce_date(m.group("start"))
            terms["period_end"] = coerce_date(m.group("end"))
        if (m := INSUREDS_RE.search(chunk.content)) and "named_insureds" not in terms:
            terms["named_insureds"] = [n.strip() for n in m.group("v").split(",") if n.strip()]
    return terms


class HeuristicInterpreter:
    """Pattern-based reading of the clause formats used in the sample policies."""

    name = "heuristic"

    def interpret(self, claim: Claim, chunks: list[PolicyChunkRef]) -> PolicyTerms:
        terms = _common_terms(claim.policy_number or "", chunks)

        if claim.claim_type:
            code = f"claim type code: {claim.claim_type.value}"
            for chunk in chunks:
                if code in chunk.content.casefold():
                    terms["claim_type_covered"] = True
                    if m := LIMIT_RE.search(chunk.content):
                        terms["coverage_limit"] = parse_amount(m.group("v"))
                    if m := DEDUCTIBLE_RE.search(chunk.content):
                        terms["deductible"] = parse_amount(m.group("v"))
                    break

        hits: list[ExclusionHit] = []
        description = (claim.description or "").casefold()
        for chunk in filter(is_exclusion_chunk, chunks):
            heading = chunk.section.split(" ", 1)[1] if " " in chunk.section else chunk.section
            keywords = [w for w in re.findall(r"[a-z][a-z\-]{4,}", heading.casefold()) if w not in _GENERIC]
            matched = [
                k for k in keywords if re.search(rf"\b{re.escape(k[:-1] if k.endswith('s') else k)}", description)
            ]
            if matched:
                hits.append(ExclusionHit(clause=chunk.section, reason=f"Claim description mentions '{matched[0]}'."))
        terms["triggered_exclusions"] = hits
        return PolicyTerms(interpreter=self.name, **terms)


class _ExclusionHitLLM(BaseModel):
    clause: str = Field(description="The clause section label exactly as given, e.g. '2.1 Racing'.")
    reason: str = Field(description="One sentence linking the claim facts to the clause.")


class PolicyTermsExtraction(BaseModel):
    period_start: str | None = Field(description="Policy period start date, YYYY-MM-DD.")
    period_end: str | None = Field(description="Policy period end date, YYYY-MM-DD.")
    named_insureds: list[str]
    claim_type_covered: bool = Field(description="True if a coverage clause covers this claim type.")
    coverage_limit: float | None = Field(description="Per-claim limit of liability for this claim type.")
    deductible: float | None
    triggered_exclusions: list[_ExclusionHitLLM]


INTERPRETER_SYSTEM = """You read excerpts of an insurance policy and report the terms that \
apply to one claim. Use only the policy excerpts provided; if a term is not present in them, \
return null (or false / an empty list). Report an exclusion only when the claim facts clearly \
fall within that clause; do not report exclusions on speculation. You are not deciding the \
claim — downstream rules do that from the terms you report."""


class ClaudeInterpreter:
    name = "claude"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def interpret(self, claim: Claim, chunks: list[PolicyChunkRef]) -> PolicyTerms:
        from app.services.llm import structured_call

        excerpts = "\n\n".join(f'<clause section="{c.section}">\n{c.content}\n</clause>' for c in chunks)
        facts = {
            "policy_number": claim.policy_number,
            "claimant_name": claim.claimant_name,
            "incident_date": claim.incident_date.isoformat() if claim.incident_date else None,
            "amount": claim.amount,
            "claim_type": claim.claim_type.value if claim.claim_type else None,
            "claim_type_label": CLAIM_TYPE_LABELS[claim.claim_type] if claim.claim_type else None,
            "description": claim.description,
        }
        result = structured_call(
            self.settings,
            system=INTERPRETER_SYSTEM,
            content=[
                {
                    "type": "text",
                    "text": f"<policy_excerpts>\n{excerpts}\n</policy_excerpts>\n\n"
                    f"<claim>\n{json.dumps(facts, indent=2)}\n</claim>\n\n"
                    "Report the policy terms that apply to this claim.",
                }
            ],
            schema=PolicyTermsExtraction,
        )
        known_sections = {c.section for c in chunks}
        return PolicyTerms(
            policy_number=claim.policy_number or "",
            period_start=coerce_date(result.period_start),
            period_end=coerce_date(result.period_end),
            named_insureds=result.named_insureds,
            claim_type_covered=result.claim_type_covered,
            coverage_limit=result.coverage_limit,
            deductible=result.deductible,
            triggered_exclusions=[
                ExclusionHit(clause=h.clause, reason=h.reason)
                for h in result.triggered_exclusions
                if h.clause in known_sections
            ],
            interpreter=self.name,
        )


def get_interpreter(settings: Settings, kind: str | None = None) -> Interpreter:
    kind = kind or settings.resolved_extractor()
    return ClaudeInterpreter(settings) if kind == "claude" else HeuristicInterpreter()
