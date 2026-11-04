"""Parsing and normalisation helpers for dates, amounts, names and identifiers."""

from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = {
    m.lower(): i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(r"\b(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{4})\b"),  # day-first
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RE})\.?,?\s+(?P<y>\d{{4}})\b", re.I),
    re.compile(rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I),
)

AMOUNT_RE = re.compile(
    r"(?:(?P<cur>USD|US\$|\$)\s?)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+\.\d{2}|\d+)"
    r"(?:\s?(?P<cur2>USD|dollars))?",
    re.I,
)


def parse_date(text: str | None) -> date | None:
    """Parse the first date found in ``text``. Slash dates are read day-first."""
    if not text:
        return None
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        parts = match.groupdict()
        month = _MONTHS[parts["mon"].lower()] if parts.get("mon") else int(parts["m"])
        try:
            return date(int(parts["y"]), month, int(parts["d"]))
        except ValueError:
            continue
    return None


def find_dates(text: str) -> list[tuple[date, int, int]]:
    """All dates in ``text`` as (date, start, end), in document order."""
    found: dict[int, tuple[date, int, int]] = {}
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            parsed = parse_date(match.group(0))
            if parsed and not any(s <= match.start() < e for _, s, e in found.values()):
                found[match.start()] = (parsed, match.start(), match.end())
    return [found[k] for k in sorted(found)]


def parse_amount(text: str | None) -> float | None:
    """Parse a monetary amount such as ``$4,250.00``, ``USD 1,180.50`` or ``1180.50``."""
    if not text:
        return None
    match = AMOUNT_RE.search(text)
    if not match:
        return None
    try:
        return round(float(match.group("num").replace(",", "")), 2)
    except ValueError:
        return None


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = normalize_space(re.sub(r"[^\w\s'.-]", " ", name))
    return cleaned.casefold() or None


def normalize_policy_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned or None


def text_contains(haystack: str, needle: str) -> bool:
    """Whitespace- and case-insensitive containment, used to ground extracted evidence."""
    if not needle:
        return False
    return normalize_space(needle).casefold() in normalize_space(haystack).casefold()


def coerce_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return parse_date(value)
