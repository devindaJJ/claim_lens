"""Deterministic policy rules evaluated against interpreted policy terms."""

from __future__ import annotations

from app.schemas.domain import (
    CLAIM_TYPE_LABELS,
    Claim,
    PolicyChunkRef,
    PolicyTerms,
    RuleCode,
    RuleResult,
)
from app.services.normalize import normalize_name


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _evidence(chunks: list[PolicyChunkRef], predicate) -> list[PolicyChunkRef]:
    return [c for c in chunks if predicate(c)]


def check_required_fields(claim: Claim) -> RuleResult:
    missing = claim.missing_required()
    if missing:
        return RuleResult(
            code=RuleCode.REQUIRED_FIELDS,
            passed=False,
            message="Missing required field(s): " + ", ".join(m.replace("_", " ") for m in missing),
        )
    return RuleResult(code=RuleCode.REQUIRED_FIELDS, passed=True, message="All required fields present.")


def evaluate_rules(claim: Claim, terms: PolicyTerms, chunks: list[PolicyChunkRef]) -> list[RuleResult]:
    """Evaluate the rules that can be evaluated given the claim fields available."""
    results: list[RuleResult] = []
    declarations = _evidence(chunks, lambda c: c.section == "Declarations")

    if claim.claimant_name:
        insureds = {normalize_name(n) for n in terms.named_insureds}
        ok = normalize_name(claim.claimant_name) in insureds
        results.append(
            RuleResult(
                code=RuleCode.CLAIMANT_INSURED,
                passed=ok,
                message=(
                    f"{claim.claimant_name} is a named insured."
                    if ok
                    else f"{claim.claimant_name} is not a named insured"
                    + (f" (named insureds: {', '.join(terms.named_insureds)})." if terms.named_insureds else ".")
                ),
                evidence=declarations,
            )
        )

    if claim.incident_date:
        start, end = terms.period_start, terms.period_end
        if start is None or end is None:
            results.append(
                RuleResult(
                    code=RuleCode.INCIDENT_IN_PERIOD,
                    passed=False,
                    message="Could not determine the policy period from the policy document.",
                )
            )
        else:
            ok = start <= claim.incident_date <= end
            results.append(
                RuleResult(
                    code=RuleCode.INCIDENT_IN_PERIOD,
                    passed=ok,
                    message=(
                        f"Incident date {claim.incident_date.isoformat()} is "
                        f"{'within' if ok else 'outside'} the policy period {start.isoformat()} to {end.isoformat()}."
                    ),
                    evidence=declarations,
                )
            )

    if claim.claim_type:
        label = CLAIM_TYPE_LABELS[claim.claim_type]
        coverage = _evidence(chunks, lambda c: claim.claim_type.value in c.content or label in c.section)
        results.append(
            RuleResult(
                code=RuleCode.COVERAGE_APPLIES,
                passed=terms.claim_type_covered,
                message=(
                    f"The policy provides {label} coverage."
                    if terms.claim_type_covered
                    else f"No {label} coverage found in this policy."
                ),
                evidence=coverage,
            )
        )
        if terms.claim_type_covered and claim.amount is not None:
            if terms.coverage_limit is None:
                results.append(
                    RuleResult(
                        code=RuleCode.WITHIN_LIMIT,
                        passed=False,
                        message=f"Could not determine the {label} limit from the policy document.",
                        evidence=coverage,
                    )
                )
            else:
                ok = claim.amount <= terms.coverage_limit
                deductible = f" Deductible {_money(terms.deductible)} applies." if terms.deductible else ""
                results.append(
                    RuleResult(
                        code=RuleCode.WITHIN_LIMIT,
                        passed=ok,
                        message=(
                            f"Amount {_money(claim.amount)} is {'within' if ok else 'above'} the "
                            f"{label} limit of {_money(terms.coverage_limit)}.{deductible}"
                        ),
                        evidence=coverage,
                    )
                )

    hits = terms.triggered_exclusions
    hit_sections = {h.clause for h in hits}
    results.append(
        RuleResult(
            code=RuleCode.NO_EXCLUSION,
            passed=not hits,
            message=(
                "No policy exclusion applies."
                if not hits
                else "Exclusion applies: " + "; ".join(f"{h.clause} – {h.reason}" for h in hits)
            ),
            evidence=_evidence(chunks, lambda c: c.section in hit_sections),
        )
    )
    return results
