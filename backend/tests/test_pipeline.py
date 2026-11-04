"""End-to-end pipeline tests over the synthetic dataset, using the offline baseline."""

import json
import shutil

import pytest

from app.config import get_settings
from app.schemas.domain import Route, RuleCode
from app.services.pipeline import Pipeline


@pytest.fixture(scope="module")
def pipeline(retriever):
    return Pipeline.create(get_settings(), retriever, "heuristic")


def _truth(data_dir, claim_id):
    return json.loads((data_dir / "ground_truth" / f"{claim_id}.json").read_text())


def test_retrieval_targets_the_right_sections(retriever):
    hits = retriever.search(
        "DM-AUTO-2025-001", "Excluded cause of loss: car spun off during a track racing day", 3, "exclusions"
    )
    assert hits[0].section == "2.1 Racing"
    assert all("EXCLUSIONS" in h.group for h in hits)
    assert retriever.search("DM-NOPE-0000-000", "anything", 3) == []


@pytest.mark.parametrize("claim_id", ["CLM-2025-0001", "CLM-2025-0013", "CLM-2025-0019"])
def test_clean_form_claims_are_auto_approved(pipeline, data_dir, claim_id):
    result = pipeline.run(data_dir / "claims" / f"{claim_id}.pdf")
    assert result.routing.route == Route.AUTO_APPROVED, result.routing.reasons
    assert all(r.passed for r in result.rules)


@pytest.mark.parametrize(
    ("claim_id", "rule"),
    [
        ("CLM-2025-0004", RuleCode.INCIDENT_IN_PERIOD),
        ("CLM-2025-0006", RuleCode.CLAIMANT_INSURED),
        ("CLM-2025-0017", RuleCode.WITHIN_LIMIT),
        ("CLM-2025-0018", RuleCode.REQUIRED_FIELDS),
        ("CLM-2025-0023", RuleCode.POLICY_FOUND),
    ],
)
def test_rule_failures_route_to_review(pipeline, data_dir, claim_id, rule):
    result = pipeline.run(data_dir / "claims" / f"{claim_id}.pdf")
    failed = {r.code for r in result.rules if not r.passed}
    assert failed == {rule}
    assert {f.value for f in failed} == set(_truth(data_dir, claim_id)["expected_failed_rules"])
    assert result.routing.route == Route.NEEDS_REVIEW


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_scanned_claim_is_ocrd(pipeline, data_dir):
    result = pipeline.run(data_dir / "claims" / "CLM-2025-0007.pdf")
    assert result.document.method == "ocr"
    assert result.extraction.claim.policy_number == "DM-AUTO-2025-001"
    assert result.extraction.claim.amount == 22500.0
