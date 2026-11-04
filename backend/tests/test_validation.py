from datetime import date

from app.schemas.domain import Claim, ClaimType, ExclusionHit, FieldMeta, PolicyChunkRef, PolicyTerms, Route, RuleCode
from app.services.interpretation import HeuristicInterpreter
from app.services.pipeline import route_claim
from app.services.rag.chunking import chunk_policy
from app.services.validation import check_required_fields, evaluate_rules

POLICY_TEXT = """PERSONAL AUTO POLICY
DECLARATIONS
Policy Number: DM-AUTO-2025-001
Policyholder: Amara Perera
Named Insureds: Amara Perera, Nuwan Perera
Policy Period: 2025-01-01 to 2025-12-31
SECTION 1 - COVERAGES AND LIMITS
1.1 Collision. We will pay for collision damage. Claim type code: auto_collision.
Limit of liability per claim: $25,000.00. Deductible: $500.00 per claim.
SECTION 2 - EXCLUSIONS
We will not pay for any claim to which one of the following exclusions applies.
2.1 Racing. Loss arising while the vehicle is used for racing.
2.2 Intoxication. Loss while driven under the influence."""

TERMS = PolicyTerms(
    policy_number="DM-AUTO-2025-001",
    period_start=date(2025, 1, 1),
    period_end=date(2025, 12, 31),
    named_insureds=["Amara Perera", "Nuwan Perera"],
    claim_type_covered=True,
    coverage_limit=25_000,
    deductible=500,
)


def _claim(**overrides) -> Claim:
    base = dict(
        policy_number="DM-AUTO-2025-001",
        claimant_name="Amara Perera",
        incident_date=date(2025, 3, 14),
        amount=4250.0,
        claim_type=ClaimType.AUTO_COLLISION,
        description="Rear-ended at a light.",
    )
    return Claim(**(base | overrides))


def _failed(claim: Claim, terms: PolicyTerms = TERMS) -> set[str]:
    return {r.code.value for r in evaluate_rules(claim, terms, []) if not r.passed}


def _refs(text: str) -> list[PolicyChunkRef]:
    parsed = chunk_policy(text)
    return [
        PolicyChunkRef(
            chunk_id=str(c.index),
            policy_number=parsed.policy_number,
            section=c.section,
            group=c.group,
            content=c.content,
        )
        for c in parsed.chunks
    ]


def test_chunking_splits_clauses():
    parsed = chunk_policy(POLICY_TEXT)
    sections = [c.section for c in parsed.chunks]
    assert parsed.policy_number == "DM-AUTO-2025-001"
    assert parsed.title == "Personal Auto Policy"
    assert sections == ["Declarations", "1.1 Collision", "SECTION 2 - EXCLUSIONS", "2.1 Racing", "2.2 Intoxication"]


def test_valid_claim_passes_every_rule():
    assert _failed(_claim()) == set()


def test_each_rule_fails_independently():
    assert _failed(_claim(claimant_name="Kasun Silva")) == {"claimant_insured"}
    assert _failed(_claim(incident_date=date(2026, 1, 1))) == {"incident_in_period"}
    assert _failed(_claim(amount=25_000.01)) == {"within_limit"}
    assert _failed(_claim(), TERMS.model_copy(update={"claim_type_covered": False})) == {"coverage_applies"}
    hit = ExclusionHit(clause="2.1 Racing", reason="Track day.")
    assert _failed(_claim(), TERMS.model_copy(update={"triggered_exclusions": [hit]})) == {"no_exclusion"}


def test_period_boundaries_are_inclusive():
    assert _failed(_claim(incident_date=date(2025, 1, 1))) == set()
    assert _failed(_claim(incident_date=date(2025, 12, 31))) == set()


def test_required_fields():
    result = check_required_fields(_claim(amount=None))
    assert not result.passed and "amount" in result.message


def test_heuristic_interpreter_reads_terms():
    terms = HeuristicInterpreter().interpret(_claim(), _refs(POLICY_TEXT))
    assert terms.period_start == date(2025, 1, 1) and terms.period_end == date(2025, 12, 31)
    assert terms.named_insureds == ["Amara Perera", "Nuwan Perera"]
    assert terms.claim_type_covered and terms.coverage_limit == 25_000 and terms.deductible == 500
    assert terms.triggered_exclusions == []


def test_heuristic_interpreter_flags_keyword_exclusion():
    terms = HeuristicInterpreter().interpret(
        _claim(description="Spun off during a track racing day."), _refs(POLICY_TEXT)
    )
    assert [h.clause for h in terms.triggered_exclusions] == ["2.1 Racing"]


def test_routing():
    fields = {"policy_number": FieldMeta(confidence=0.95), "amount": FieldMeta(confidence=0.4)}
    decision = route_claim(fields, [], threshold=0.8)
    assert decision.route == Route.NEEDS_REVIEW
    assert decision.reasons == ["Low confidence on amount (0.40)"]
    confident = {k: FieldMeta(confidence=0.9) for k in fields}
    assert route_claim(confident, [], threshold=0.8).route == Route.AUTO_APPROVED
    rules = evaluate_rules(_claim(amount=99_999), TERMS, [])
    assert route_claim(confident, rules, threshold=0.8).route == Route.NEEDS_REVIEW
    assert any(r.code == RuleCode.WITHIN_LIMIT and not r.passed for r in rules)
