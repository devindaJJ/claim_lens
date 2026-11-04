from evaluation.metrics import FieldScore, values_match


def test_values_match_normalises_per_field():
    assert values_match("amount", 4250.004, 4250.0)
    assert values_match("claimant_name", "amara  PERERA", "Amara Perera")
    assert values_match("policy_number", "dm-auto-2025-001", "DM-AUTO-2025-001")
    assert values_match("incident_date", None, None)
    assert not values_match("incident_date", "2025-03-14", None)


def test_field_score_counts():
    score = FieldScore()
    score.add("amount", 10.0, 10.0)  # TP
    score.add("amount", 11.0, 10.0)  # wrong value: FP + FN
    score.add("amount", None, 10.0)  # missed: FN
    score.add("amount", 5.0, None)  # hallucinated: FP
    score.add("amount", None, None)  # TN
    assert (score.tp, score.fp, score.fn, score.tn) == (1, 2, 2, 1)
    assert score.precision == 1 / 3
    assert score.recall == 1 / 3
