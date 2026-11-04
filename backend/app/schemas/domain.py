"""Core domain types shared by the pipeline, API, worker and evaluation harness."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    AUTO_COLLISION = "auto_collision"
    AUTO_THEFT = "auto_theft"
    AUTO_GLASS = "auto_glass"
    HOME_WATER_DAMAGE = "home_water_damage"
    HOME_FIRE = "home_fire"
    HOME_THEFT = "home_theft"
    HEALTH_HOSPITALIZATION = "health_hospitalization"
    HEALTH_OUTPATIENT = "health_outpatient"
    HEALTH_DENTAL = "health_dental"
    TRAVEL_CANCELLATION = "travel_cancellation"
    TRAVEL_MEDICAL = "travel_medical"
    TRAVEL_BAGGAGE = "travel_baggage"


CLAIM_TYPE_LABELS: dict[ClaimType, str] = {
    ClaimType.AUTO_COLLISION: "Collision",
    ClaimType.AUTO_THEFT: "Theft of Vehicle",
    ClaimType.AUTO_GLASS: "Glass Breakage",
    ClaimType.HOME_WATER_DAMAGE: "Water Damage",
    ClaimType.HOME_FIRE: "Fire Damage",
    ClaimType.HOME_THEFT: "Burglary / Theft",
    ClaimType.HEALTH_HOSPITALIZATION: "Hospitalization",
    ClaimType.HEALTH_OUTPATIENT: "Outpatient Treatment",
    ClaimType.HEALTH_DENTAL: "Dental Treatment",
    ClaimType.TRAVEL_CANCELLATION: "Trip Cancellation",
    ClaimType.TRAVEL_MEDICAL: "Emergency Medical",
    ClaimType.TRAVEL_BAGGAGE: "Lost or Delayed Baggage",
}

# Fields that make up a claim. Order matters for display.
CLAIM_FIELDS: tuple[str, ...] = (
    "policy_number",
    "claimant_name",
    "incident_date",
    "amount",
    "claim_type",
)
REQUIRED_FIELDS = CLAIM_FIELDS


class Claim(BaseModel):
    """A normalised claim, as extracted from a claim packet (or corrected by a reviewer)."""

    policy_number: str | None = None
    claimant_name: str | None = None
    incident_date: date | None = None
    amount: float | None = Field(default=None, ge=0)
    claim_type: ClaimType | None = None
    description: str | None = None

    def missing_required(self) -> list[str]:
        return [name for name in REQUIRED_FIELDS if getattr(self, name) is None]


class FieldMeta(BaseModel):
    """Provenance and confidence for one extracted field."""

    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None
    grounded: bool = False


class ExtractionResult(BaseModel):
    claim: Claim
    fields: dict[str, FieldMeta]
    extractor: str


class PageText(BaseModel):
    page: int
    text: str
    method: str  # "pdf_text" | "ocr"
    ocr_confidence: float | None = None  # 0..1, OCR pages only


class DocumentText(BaseModel):
    pages: list[PageText]

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def method(self) -> str:
        methods = {p.method for p in self.pages}
        if methods == {"ocr"}:
            return "ocr"
        if "ocr" in methods:
            return "mixed"
        return "pdf_text"

    @property
    def ocr_confidence(self) -> float | None:
        scores = [p.ocr_confidence for p in self.pages if p.ocr_confidence is not None]
        return sum(scores) / len(scores) if scores else None


class PolicyChunkRef(BaseModel):
    chunk_id: str
    policy_number: str
    section: str
    group: str = ""
    content: str
    score: float | None = None


class ExclusionHit(BaseModel):
    clause: str
    reason: str


class PolicyTerms(BaseModel):
    """The policy terms relevant to one claim, interpreted from retrieved policy clauses."""

    policy_number: str
    period_start: date | None = None
    period_end: date | None = None
    named_insureds: list[str] = Field(default_factory=list)
    claim_type_covered: bool = False
    coverage_limit: float | None = None
    deductible: float | None = None
    triggered_exclusions: list[ExclusionHit] = Field(default_factory=list)
    interpreter: str = "heuristic"


class RuleCode(StrEnum):
    REQUIRED_FIELDS = "required_fields"
    POLICY_FOUND = "policy_found"
    CLAIMANT_INSURED = "claimant_insured"
    INCIDENT_IN_PERIOD = "incident_in_period"
    COVERAGE_APPLIES = "coverage_applies"
    WITHIN_LIMIT = "within_limit"
    NO_EXCLUSION = "no_exclusion"


class RuleResult(BaseModel):
    code: RuleCode
    passed: bool
    message: str
    evidence: list[PolicyChunkRef] = Field(default_factory=list)


class Route(StrEnum):
    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"


class RoutingDecision(BaseModel):
    route: Route
    reasons: list[str]


class ProcessingResult(BaseModel):
    document: DocumentText
    extraction: ExtractionResult
    rules: list[RuleResult]
    routing: RoutingDecision
