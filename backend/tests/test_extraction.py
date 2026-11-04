from datetime import date

from anthropic.lib._parse._transform import transform_schema

from app.schemas.domain import ClaimType
from app.services.confidence import UNGROUNDED_CAP, calibrate
from app.services.extraction.claude import ClaimExtraction, to_extraction_result
from app.services.extraction.heuristic import HeuristicExtractor, match_claim_type
from tests.conftest import doc

FORM = """Northwind Demo Assurance (fictional)
Claim Notification Form
Policy Number
DM-AUTO-2025-001
Claimant Name
Amara Perera
Date of Loss (DD/MM/YYYY)
14/03/2025
Type of Claim
Collision
Amount Claimed
$4,250.00
Date Reported
17/03/2025
Description of Incident
Rear-ended at a traffic light.
I declare that the information given is true."""

LETTER = """June 9, 2025
Claims Department
Re: Glass Breakage claim
Dear Sir or Madam,
I, Nuwan Perera, hold cover under policy DM-AUTO-2025-001 and would like to submit a
claim for an incident that happened on 2 June 2025.
A stone cracked the windscreen.
The total amount I am claiming is 1180.50, as shown on the attached receipts.
Yours faithfully,
Nuwan Perera"""


def test_heuristic_form():
    result = HeuristicExtractor().extract(doc(FORM))
    claim = result.claim
    assert claim.policy_number == "DM-AUTO-2025-001"
    assert claim.claimant_name == "Amara Perera"
    assert claim.incident_date == date(2025, 3, 14)  # not the reported date
    assert claim.amount == 4250.0
    assert claim.claim_type == ClaimType.AUTO_COLLISION
    assert claim.description == "Rear-ended at a traffic light."
    assert all(m.grounded and m.confidence >= 0.9 for m in result.fields.values())


def test_heuristic_letter_uses_incident_date_not_letter_date():
    claim = HeuristicExtractor().extract(doc(LETTER)).claim
    assert claim.claimant_name == "Nuwan Perera"
    assert claim.incident_date == date(2025, 6, 2)
    assert claim.amount == 1180.5
    assert claim.claim_type == ClaimType.AUTO_GLASS
    assert claim.description == "A stone cracked the windscreen."


def test_heuristic_missing_amount_is_null_with_zero_confidence():
    result = HeuristicExtractor().extract(
        doc(LETTER.replace("The total amount I am claiming is 1180.50, as shown", "Invoice"))
    )
    assert result.claim.amount is None
    assert result.fields["amount"].confidence == 0


def test_claim_type_respects_policy_line():
    assert match_claim_type("Burglary / Theft", "DM-HOME-2025-002") == ClaimType.HOME_THEFT
    assert match_claim_type("Theft of Vehicle", "DM-AUTO-2025-001") == ClaimType.AUTO_THEFT


def test_calibration_caps_ungrounded_values_and_discounts_ocr():
    document = doc("Policy Number DM-AUTO-2025-001")
    assert calibrate("X", 0.99, "not in the text", document).confidence == UNGROUNDED_CAP
    assert calibrate("X", 0.99, "DM-AUTO-2025-001", document).confidence == 0.99
    assert calibrate(None, 0.99, None, document).confidence == 0
    ocr_doc = doc("Policy Number DM-AUTO-2025-001", method="ocr", ocr=0.5)
    assert calibrate("X", 1.0, "DM-AUTO-2025-001", ocr_doc).confidence == 0.8


def test_claude_schema_is_structured_output_compatible():
    schema = transform_schema(ClaimExtraction)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) >= {"policy_number", "claimant_name", "incident_date", "amount", "claim_type"}


def test_claude_result_mapping():
    parsed = ClaimExtraction.model_validate(
        {
            "policy_number": {"value": " dm-auto-2025-001 ", "confidence": 0.97, "evidence": "DM-AUTO-2025-001"},
            "claimant_name": {"value": "Amara Perera", "confidence": 0.95, "evidence": "Amara Perera"},
            "incident_date": {"value": "2025-03-14", "confidence": 0.9, "evidence": "14/03/2025"},
            "amount": {"value": 4250, "confidence": 0.9, "evidence": "made up"},
            "claim_type": {"value": "auto_collision", "confidence": 0.9, "evidence": "Collision"},
            "incident_description": "Rear-ended.",
        }
    )
    result = to_extraction_result(parsed, doc(FORM))
    assert result.claim.policy_number == "DM-AUTO-2025-001"
    assert result.claim.incident_date == date(2025, 3, 14)
    assert result.fields["amount"].grounded is False
    assert result.fields["amount"].confidence == UNGROUNDED_CAP
    assert result.fields["policy_number"].confidence == 0.97


def test_heuristic_tolerates_ocr_table_borders():
    ocr = "Policy Number | DM-HLTH-2025-003\nClaimant Name | Lucas Martinez\nDate of Loss (DD/MM/YYYY) | 19/05/2025 |"
    claim = HeuristicExtractor().extract(doc(ocr, method="ocr", ocr=0.95)).claim
    assert claim.claimant_name == "Lucas Martinez"
    assert claim.incident_date == date(2025, 5, 19)
