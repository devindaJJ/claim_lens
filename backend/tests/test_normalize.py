from datetime import date

import pytest

from app.services.normalize import coerce_date, find_dates, normalize_name, parse_amount, parse_date, text_contains


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-03-14", date(2025, 3, 14)),
        ("14/03/2025", date(2025, 3, 14)),
        ("on 2 June 2025.", date(2025, 6, 2)),
        ("June 2, 2025", date(2025, 6, 2)),
        ("the 21st of August 2025", date(2025, 8, 21)),
        ("Sept 9 2025", date(2025, 9, 9)),
        ("31/02/2025", None),
        ("no date here", None),
        (None, None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$4,250.00", 4250.0),
        ("USD 1,180.50", 1180.5),
        ("1180.50", 1180.5),
        ("27900", 27900.0),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_find_dates_in_order():
    found = find_dates("Signed 17/03/2025. Loss on 14 March 2025.")
    assert [d for d, _, _ in found] == [date(2025, 3, 17), date(2025, 3, 14)]


def test_names_and_containment():
    assert normalize_name("  Amara   PERERA ") == "amara perera"
    assert text_contains("Claimant Name\nAmara  Perera", "claimant name amara perera")
    assert not text_contains("anything", "")


def test_coerce_date():
    assert coerce_date("2025-01-02") == date(2025, 1, 2)
    assert coerce_date("2 January 2025") == date(2025, 1, 2)
    assert coerce_date("") is None
