"""Deterministic regex baseline extractor.

It needs no network or credentials, so the pipeline, tests and evaluation harness run
anywhere. It handles labelled claim forms well and narrative letters only partially; the
evaluation report compares it with the Claude extractor.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.domain import CLAIM_TYPE_LABELS, Claim, ClaimType, DocumentText, ExtractionResult
from app.services.confidence import calibrate
from app.services.normalize import parse_amount, parse_date

POLICY_NUMBER_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z]{2,5}-\d{4}-\d{3,4}\b")
POLICY_LABEL_RE = re.compile(r"polic(?:y|ies)\s*(?:number|no\.?|ref\.?|#)?", re.I)

# Label, optional separator / "(DD/MM/YYYY)" hint, then the value up to the end of the line.
# "|" is treated as a separator because OCR reads table cell borders as pipes.
_LABEL_TAIL = r"\s*[:\-|]*\s*(?:\([^)\n]*\))?\s*[:|]*\s*(?P<v>[^\n|]+)"


def _labelled(*labels: str) -> re.Pattern[str]:
    return re.compile(rf"(?:{'|'.join(labels)}){_LABEL_TAIL}", re.I)


CLAIMANT_LABEL_RE = _labelled(r"claimant\s+name", r"name\s+of\s+insured\s+person", r"insured\s+name", r"claimant")
DATE_LABEL_RE = _labelled(r"date\s+of\s+(?:loss|incident|event)", r"incident\s+date", r"loss\s+date")
AMOUNT_LABEL_RE = _labelled(
    r"amount\s+claimed", r"total\s+claim(?:ed)?\s+(?:value|amount)", r"claim\s+amount", r"total\s+claimed"
)
TYPE_LABEL_RE = _labelled(r"type\s+of\s+claim", r"claim\s+(?:category|type)")

# Names are matched case-sensitively; only the lead-in phrases ignore case.
NAME = r"(?P<name>[A-Z][a-z'\-]+(?:[ \t]+[A-Z][a-z'\-]+){1,3})"
CLAIMANT_NARRATIVE = (
    re.compile(rf"(?i:my\s+name\s+is)\s+{NAME}"),
    re.compile(rf"\bI,\s+{NAME},"),
    re.compile(rf"\bI\s+am\s+{NAME}\s*\("),
    re.compile(rf"(?i:yours\s+(?:faithfully|sincerely)),?\s*\n\s*{NAME}"),
)
BOILERPLATE_RE = re.compile(
    r"\b(?:policy|claim(?:ing)?|amount|receipts?|invoice|let me know|reached|dear|regards)\b", re.I
)
DATE_NARRATIVE_RE = re.compile(
    r"(?:took\s+place|happened|occurred|incident|loss|accident)\s+(?:\w+\s+){0,3}?on\s+(?P<v>[^\n.]{6,30})",
    re.I,
)
AMOUNT_NARRATIVE_RE = re.compile(
    r"(?:amount\s+(?:I\s+am\s+)?claim(?:ing|ed)?\s+is|claiming\s+(?:a\s+total\s+of\s+)?|total\s+of)\s*(?P<v>(?:USD|\$)?\s?[\d,]+(?:\.\d{2})?)",
    re.I,
)
TYPE_NARRATIVE_RE = re.compile(r"\bRe:\s*(?P<v>[^\n]+?)\s+claim\b", re.I)

LINE_BY_CODE = {"AUTO": "auto", "HOME": "home", "HLTH": "health", "TRVL": "travel"}

# Synonyms used to map free-text claim categories onto claim types, per policy line.
TYPE_SYNONYMS: dict[ClaimType, tuple[str, ...]] = {
    ClaimType.AUTO_COLLISION: ("collision", "accident", "crash"),
    ClaimType.AUTO_THEFT: ("theft of vehicle", "vehicle theft", "stolen", "theft"),
    ClaimType.AUTO_GLASS: ("glass", "windscreen", "windshield"),
    ClaimType.HOME_WATER_DAMAGE: ("water damage", "escape of water", "water"),
    ClaimType.HOME_FIRE: ("fire", "smoke"),
    ClaimType.HOME_THEFT: ("burglary", "theft"),
    ClaimType.HEALTH_HOSPITALIZATION: ("hospitalization", "hospitalisation", "inpatient", "hospital"),
    ClaimType.HEALTH_OUTPATIENT: ("outpatient",),
    ClaimType.HEALTH_DENTAL: ("dental", "dentist"),
    ClaimType.TRAVEL_CANCELLATION: ("cancellation", "cancelled"),
    ClaimType.TRAVEL_MEDICAL: ("emergency medical", "medical"),
    ClaimType.TRAVEL_BAGGAGE: ("baggage", "luggage", "suitcase"),
}


def match_claim_type(text: str, policy_number: str | None) -> ClaimType | None:
    lowered = text.casefold()
    line = None
    if policy_number:
        parts = policy_number.split("-")
        line = LINE_BY_CODE.get(parts[1]) if len(parts) > 1 else None
    for claim_type, label in CLAIM_TYPE_LABELS.items():
        if label.casefold() in lowered and (line is None or claim_type.value.startswith(line)):
            return claim_type
    for claim_type, synonyms in TYPE_SYNONYMS.items():
        if line and not claim_type.value.startswith(line):
            continue
        if any(re.search(rf"\b{re.escape(s)}", lowered) for s in synonyms):
            return claim_type
    return None


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, document: DocumentText, pdf_path: Path | None = None) -> ExtractionResult:
        text = document.text
        raw: dict[str, tuple[object | None, float, str | None]] = {}

        # Policy number: the identifier format is distinctive; prefer one near a "policy" label.
        policy, policy_conf, policy_ev = None, 0.0, None
        for match in POLICY_NUMBER_RE.finditer(text):
            window = text[max(0, match.start() - 40) : match.start()]
            conf = 0.95 if POLICY_LABEL_RE.search(window) else 0.75
            if conf > policy_conf:
                policy, policy_conf, policy_ev = match.group(0), conf, match.group(0)
        raw["policy_number"] = (policy, policy_conf, policy_ev)

        raw["claimant_name"] = self._claimant(text)
        raw["incident_date"] = self._incident_date(text)
        raw["amount"] = self._amount(text)
        raw["claim_type"] = self._claim_type(text, policy)

        description = self._description(text)
        claim = Claim(
            policy_number=policy,
            claimant_name=raw["claimant_name"][0],  # type: ignore[arg-type]
            incident_date=raw["incident_date"][0],  # type: ignore[arg-type]
            amount=raw["amount"][0],  # type: ignore[arg-type]
            claim_type=raw["claim_type"][0],  # type: ignore[arg-type]
            description=description,
        )
        fields = {name: calibrate(value, conf, ev, document) for name, (value, conf, ev) in raw.items()}
        return ExtractionResult(claim=claim, fields=fields, extractor=self.name)

    @staticmethod
    def _claimant(text: str) -> tuple[str | None, float, str | None]:
        if match := CLAIMANT_LABEL_RE.search(text):
            value = match.group("v").strip()
            if re.fullmatch(r"[A-Za-z][A-Za-z'.\- ]{2,60}", value):
                return value, 0.92, value
        for conf, pattern in zip((0.8, 0.8, 0.8, 0.65), CLAIMANT_NARRATIVE, strict=True):
            if match := pattern.search(text):
                return match.group("name"), conf, match.group("name")
        return None, 0.0, None

    @staticmethod
    def _incident_date(text: str) -> tuple[object | None, float, str | None]:
        if (match := DATE_LABEL_RE.search(text)) and (parsed := parse_date(match.group("v"))):
            return parsed, 0.92, match.group("v").strip()
        if (match := DATE_NARRATIVE_RE.search(text)) and (parsed := parse_date(match.group("v"))):
            return parsed, 0.75, match.group("v").strip()
        return None, 0.0, None

    @staticmethod
    def _amount(text: str) -> tuple[object | None, float, str | None]:
        if (match := AMOUNT_LABEL_RE.search(text)) and (parsed := parse_amount(match.group("v"))) is not None:
            return parsed, 0.92, match.group("v").strip()
        if (match := AMOUNT_NARRATIVE_RE.search(text)) and (parsed := parse_amount(match.group("v"))) is not None:
            return parsed, 0.75, match.group("v").strip()
        return None, 0.0, None

    @staticmethod
    def _claim_type(text: str, policy: str | None) -> tuple[object | None, float, str | None]:
        for pattern, conf in ((TYPE_LABEL_RE, 0.9), (TYPE_NARRATIVE_RE, 0.75)):
            if (match := pattern.search(text)) and (parsed := match_claim_type(match.group("v"), policy)):
                return parsed, conf, match.group("v").strip()
        return None, 0.0, None

    @staticmethod
    def _description(text: str) -> str | None:
        match = re.search(
            r"(?:description\s+of\s+incident|what\s+happened\??)\s*[:\-]?\s*(?P<v>.+?)(?:\n\s*\n|I declare|$)",
            text,
            re.I | re.S,
        )
        if match:
            return re.sub(r"\s+", " ", match.group("v")).strip()
        # Letters: the narrative sentences between greeting and sign-off, minus boilerplate.
        body = re.search(r"Dear[^\n]*\n(?P<v>.+?)(?:Yours|Kind regards|Sincerely)", text, re.S)
        if not body:
            return None
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body.group("v")).strip())
        narrative = [s for s in sentences if not BOILERPLATE_RE.search(s)]
        return " ".join(narrative) or None
