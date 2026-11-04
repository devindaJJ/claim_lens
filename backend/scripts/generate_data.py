"""Generate the synthetic ClaimLens dataset.

Outputs (under --out, default ../data):
    policies/<POLICY>.pdf          4 sample policy documents
    claims/<CLAIM>.pdf             25 claim packets in three layouts (form, letter, scanned)
    ground_truth/<CLAIM>.json      expected fields and rule outcomes per claim

All names, companies and policy numbers are fictional. Output is deterministic.

    python scripts/generate_data.py --out ../data
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.domain import CLAIM_TYPE_LABELS, ClaimType  # noqa: E402

INSURER = "Northwind Demo Assurance (fictional)"

# --------------------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    claim_type: ClaimType
    description: str
    limit: float
    deductible: float


@dataclass(frozen=True)
class Exclusion:
    heading: str
    text: str


@dataclass(frozen=True)
class PolicySpec:
    number: str
    title: str
    holder: str
    named_insureds: tuple[str, ...]
    start: date
    end: date
    coverages: tuple[Coverage, ...]
    exclusions: tuple[Exclusion, ...]
    conditions: tuple[tuple[str, str], ...] = field(default_factory=tuple)


COMMON_CONDITIONS = (
    (
        "Notice of loss",
        "You must notify us of any loss as soon as reasonably possible and in any event "
        "within 30 days of the date of the incident. Late notice may reduce the amount we pay "
        "where the delay has prejudiced our ability to investigate.",
    ),
    (
        "Proof of loss",
        "You must provide receipts, invoices, reports or other documents reasonably required "
        "to support the amount claimed. We may request an independent assessment.",
    ),
    (
        "Fraud",
        "If any claim is fraudulent or exaggerated in any respect, we will not pay that claim "
        "and may cancel this policy from the date of the fraudulent act.",
    ),
    (
        "Other insurance",
        "If other insurance covers the same loss, we will pay only our proportionate share of the loss.",
    ),
)

POLICIES: tuple[PolicySpec, ...] = (
    PolicySpec(
        number="DM-AUTO-2025-001",
        title="Personal Auto Policy",
        holder="Amara Perera",
        named_insureds=("Amara Perera", "Nuwan Perera"),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        coverages=(
            Coverage(
                ClaimType.AUTO_COLLISION,
                "direct physical damage to the covered vehicle caused by collision with another vehicle or object",
                25_000,
                500,
            ),
            Coverage(
                ClaimType.AUTO_THEFT,
                "theft of the covered vehicle, or damage caused during an attempted theft",
                30_000,
                250,
            ),
            Coverage(
                ClaimType.AUTO_GLASS, "repair or replacement of broken windscreen, windows and sunroof glass", 2_000, 0
            ),
        ),
        exclusions=(
            Exclusion(
                "Racing",
                "Loss arising while the vehicle is used for racing, pace-making, speed testing or any organised track event.",
            ),
            Exclusion(
                "Intoxication",
                "Loss occurring while the vehicle is driven by a person under the influence of alcohol or drugs.",
            ),
            Exclusion(
                "Ride-sharing",
                "Loss occurring while the vehicle is used to carry passengers or goods for hire or reward, including app-based ride-sharing.",
            ),
            Exclusion(
                "Unlicensed drivers",
                "Loss occurring while the vehicle is driven by a person who does not hold a valid driving licence.",
            ),
        ),
    ),
    PolicySpec(
        number="DM-HOME-2025-002",
        title="Homeowners Policy",
        holder="Daniel Okafor",
        named_insureds=("Daniel Okafor", "Grace Okafor"),
        start=date(2025, 3, 15),
        end=date(2026, 3, 14),
        coverages=(
            Coverage(
                ClaimType.HOME_WATER_DAMAGE,
                "sudden and accidental escape of water from plumbing, heating or domestic appliances",
                15_000,
                250,
            ),
            Coverage(
                ClaimType.HOME_FIRE,
                "damage to the dwelling and contents caused by fire, smoke or explosion",
                150_000,
                1_000,
            ),
            Coverage(
                ClaimType.HOME_THEFT,
                "theft of contents following forcible and violent entry to the dwelling",
                10_000,
                250,
            ),
        ),
        exclusions=(
            Exclusion(
                "Flood",
                "Loss caused by flood, meaning water entering the dwelling from rising rivers, surface water, storm surge or overflow of natural watercourses.",
            ),
            Exclusion(
                "Gradual deterioration",
                "Loss caused by wear and tear, rot, rust, or water that has leaked gradually over a period of time.",
            ),
            Exclusion("Mold", "Loss caused by mold, mildew or fungus, regardless of any other cause."),
            Exclusion("Earthquake", "Loss caused by earthquake, landslide or other earth movement."),
        ),
    ),
    PolicySpec(
        number="DM-HLTH-2025-003",
        title="Individual Health Policy",
        holder="Sofia Martinez",
        named_insureds=("Sofia Martinez", "Lucas Martinez"),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        coverages=(
            Coverage(
                ClaimType.HEALTH_HOSPITALIZATION,
                "medically necessary inpatient treatment, surgery and accommodation in a recognised hospital",
                50_000,
                0,
            ),
            Coverage(
                ClaimType.HEALTH_OUTPATIENT,
                "consultations, diagnostic tests and therapies that do not require an overnight stay",
                5_000,
                50,
            ),
            Coverage(
                ClaimType.HEALTH_DENTAL, "routine and restorative dental treatment by a registered dentist", 1_500, 0
            ),
        ),
        exclusions=(
            Exclusion(
                "Cosmetic procedures",
                "Treatment or surgery undertaken primarily to change or improve appearance, unless required following an accident.",
            ),
            Exclusion(
                "Experimental treatment",
                "Treatment, drugs or devices that are experimental or not approved by the relevant medical authority.",
            ),
            Exclusion(
                "Pre-existing conditions",
                "Conditions for which the insured received treatment or advice in the 12 months before the policy start date.",
            ),
        ),
    ),
    PolicySpec(
        number="DM-TRVL-2025-004",
        title="Single Trip Travel Policy",
        holder="Kenji Tanaka",
        named_insureds=("Kenji Tanaka", "Yui Tanaka"),
        start=date(2025, 6, 1),
        end=date(2025, 8, 31),
        coverages=(
            Coverage(
                ClaimType.TRAVEL_CANCELLATION,
                "non-refundable travel and accommodation costs if the trip is cancelled for a covered reason",
                4_000,
                100,
            ),
            Coverage(
                ClaimType.TRAVEL_MEDICAL,
                "emergency medical and hospital expenses incurred abroad, including repatriation",
                100_000,
                100,
            ),
            Coverage(
                ClaimType.TRAVEL_BAGGAGE, "loss of, theft of, or damage to checked or personal baggage", 2_500, 50
            ),
        ),
        exclusions=(
            Exclusion(
                "Hazardous activities",
                "Injury sustained while taking part in paragliding, skydiving, bungee jumping, mountaineering above 4,000 metres or similar high-risk activities.",
            ),
            Exclusion(
                "Intoxication", "Any claim arising from the insured being under the influence of alcohol or drugs."
            ),
            Exclusion(
                "Government travel advisory",
                "Travel to a destination against the advice of the government of the insured's country of residence.",
            ),
        ),
    ),
)
POLICY_BY_NUMBER = {p.number: p for p in POLICIES}


def _money(value: float) -> str:
    return f"${value:,.2f}"


def build_policy_pdf(policy: PolicySpec, path: Path) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)

    story = [
        Paragraph(INSURER, styles["Normal"]),
        Paragraph(policy.title.upper(), h1),
        Spacer(1, 4),
        Paragraph("DECLARATIONS", h2),
        Paragraph(f"Policy Number: {policy.number}", body),
        Paragraph(f"Policyholder: {policy.holder}", body),
        Paragraph(f"Named Insureds: {', '.join(policy.named_insureds)}", body),
        Paragraph(f"Policy Period: {policy.start.isoformat()} to {policy.end.isoformat()}", body),
        Paragraph(
            "Coverage applies only to incidents that occur within the policy period, both dates "
            "inclusive, and only to claims made by a named insured.",
            body,
        ),
        Paragraph("SECTION 1 - COVERAGES AND LIMITS", h2),
    ]
    for i, cov in enumerate(policy.coverages, start=1):
        label = CLAIM_TYPE_LABELS[cov.claim_type]
        story.append(
            Paragraph(
                f"1.{i} {label}. We will pay for {cov.description}. "
                f"Claim type code: {cov.claim_type.value}. "
                f"Limit of liability per claim: {_money(cov.limit)}. "
                f"Deductible: {_money(cov.deductible)} per claim.",
                body,
            )
        )
    story.append(Paragraph("SECTION 2 - EXCLUSIONS", h2))
    story.append(Paragraph("We will not pay for any claim to which one of the following exclusions applies.", body))
    for i, exc in enumerate(policy.exclusions, start=1):
        story.append(Paragraph(f"2.{i} {exc.heading}. {exc.text}", body))
    story.append(Paragraph("SECTION 3 - CONDITIONS", h2))
    for i, (heading, text) in enumerate(COMMON_CONDITIONS + policy.conditions, start=1):
        story.append(Paragraph(f"3.{i} {heading}. {text}", body))
    story.append(Paragraph("SECTION 4 - GENERAL PROVISIONS", h2))
    story.append(
        Paragraph(
            "4.1 Cancellation. You may cancel this policy at any time by writing to us. We will "
            "refund any unearned premium on a pro-rata basis provided no claim has been paid.",
            body,
        )
    )
    story.append(
        Paragraph(
            "4.2 Governing law. This policy is governed by the laws of the jurisdiction in which "
            "it was issued. This document is a fictional sample created for software testing.",
            body,
        )
    )
    SimpleDocTemplate(
        str(path), pagesize=A4, title=f"{policy.title} {policy.number}", leftMargin=20 * mm, rightMargin=20 * mm
    ).build(story)


# --------------------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimSpec:
    layout: str  # form | letter | scanned
    policy_number: str
    claimant: str
    incident_date: date
    amount: float | None
    claim_type: ClaimType
    description: str
    expected_failed_rules: tuple[str, ...] = ()


A, H, M, T = "DM-AUTO-2025-001", "DM-HOME-2025-002", "DM-HLTH-2025-003", "DM-TRVL-2025-004"
CT = ClaimType

CLAIMS: tuple[ClaimSpec, ...] = (
    # Auto
    ClaimSpec(
        "form",
        A,
        "Amara Perera",
        date(2025, 3, 14),
        4250.00,
        CT.AUTO_COLLISION,
        "Rear-ended while stopped at a traffic light on Galle Road. Rear bumper, boot lid and tail lights damaged.",
    ),
    ClaimSpec(
        "letter",
        A,
        "Nuwan Perera",
        date(2025, 6, 2),
        1180.50,
        CT.AUTO_GLASS,
        "A stone thrown up by a lorry on the expressway cracked the windscreen across the driver's side.",
    ),
    ClaimSpec(
        "scanned",
        A,
        "Amara Perera",
        date(2025, 8, 21),
        27900.00,
        CT.AUTO_COLLISION,
        "Collided with a concrete barrier after swerving to avoid a dog. Front end and airbags require replacement.",
        ("within_limit",),
    ),
    ClaimSpec(
        "form",
        A,
        "Amara Perera",
        date(2026, 1, 9),
        3400.00,
        CT.AUTO_COLLISION,
        "Side mirror and front door damaged by a reversing delivery van in a hotel car park.",
        ("incident_in_period",),
    ),
    ClaimSpec(
        "letter",
        A,
        "Nuwan Perera",
        date(2025, 9, 30),
        8750.00,
        CT.AUTO_COLLISION,
        "The car spun off the circuit during an amateur track racing day and hit the tyre wall.",
        ("no_exclusion",),
    ),
    ClaimSpec(
        "form",
        A,
        "Kasun Silva",
        date(2025, 5, 5),
        18000.00,
        CT.AUTO_THEFT,
        "Vehicle was taken from outside a friend's house overnight. Police report filed the next morning.",
        ("claimant_insured",),
    ),
    ClaimSpec(
        "scanned",
        A,
        "Amara Perera",
        date(2025, 11, 11),
        22500.00,
        CT.AUTO_THEFT,
        "Car stolen from the supermarket car park while shopping. Keys were in the claimant's possession.",
    ),
    # Home
    ClaimSpec(
        "form",
        H,
        "Daniel Okafor",
        date(2025, 4, 22),
        6320.00,
        CT.HOME_WATER_DAMAGE,
        "Supply pipe under the kitchen sink burst and flooded the kitchen floor and lower cabinets.",
    ),
    ClaimSpec(
        "letter",
        H,
        "Grace Okafor",
        date(2025, 7, 4),
        42000.00,
        CT.HOME_FIRE,
        "A faulty toaster caught fire overnight. Kitchen units, ceiling and appliances were destroyed by fire and smoke.",
    ),
    ClaimSpec(
        "scanned",
        H,
        "Daniel Okafor",
        date(2025, 10, 18),
        9800.00,
        CT.HOME_WATER_DAMAGE,
        "After two days of heavy rain the nearby river overflowed and water entered the ground floor.",
        ("no_exclusion",),
    ),
    ClaimSpec(
        "form",
        H,
        "Daniel Okafor",
        date(2025, 2, 28),
        2300.00,
        CT.HOME_THEFT,
        "Rear door forced open while the family was away; laptop and jewellery taken.",
        ("incident_in_period",),
    ),
    ClaimSpec(
        "letter",
        H,
        "Grace Okafor",
        date(2025, 12, 1),
        12400.00,
        CT.HOME_THEFT,
        "Burglars broke a ground floor window and took a television, two laptops and a camera.",
        ("within_limit",),
    ),
    ClaimSpec(
        "form",
        H,
        "Daniel Okafor",
        date(2026, 1, 15),
        3150.00,
        CT.HOME_WATER_DAMAGE,
        "Washing machine inlet hose split during a cycle, soaking the utility room floor.",
    ),
    # Health
    ClaimSpec(
        "form",
        M,
        "Sofia Martinez",
        date(2025, 2, 10),
        12480.75,
        CT.HEALTH_HOSPITALIZATION,
        "Emergency appendectomy with three nights of inpatient care at Central General Hospital.",
    ),
    ClaimSpec(
        "scanned",
        M,
        "Lucas Martinez",
        date(2025, 5, 19),
        640.00,
        CT.HEALTH_DENTAL,
        "Root canal treatment and crown on lower left molar.",
    ),
    ClaimSpec(
        "letter",
        M,
        "Sofia Martinez",
        date(2025, 9, 3),
        3900.00,
        CT.HEALTH_OUTPATIENT,
        "Rhinoplasty consultation and procedure to reshape the nose for aesthetic reasons.",
        ("no_exclusion",),
    ),
    ClaimSpec(
        "form",
        M,
        "Sofia Martinez",
        date(2025, 11, 27),
        2150.00,
        CT.HEALTH_DENTAL,
        "Two dental implants following extraction of damaged teeth.",
        ("within_limit",),
    ),
    ClaimSpec(
        "letter",
        M,
        "Lucas Martinez",
        date(2025, 4, 8),
        None,
        CT.HEALTH_OUTPATIENT,
        "Course of physiotherapy sessions for a sprained ankle sustained playing football.",
        ("required_fields",),
    ),
    # Travel
    ClaimSpec(
        "form",
        T,
        "Kenji Tanaka",
        date(2025, 7, 12),
        1870.00,
        CT.TRAVEL_BAGGAGE,
        "Checked suitcase lost by the airline on a connecting flight; not recovered after 21 days.",
    ),
    ClaimSpec(
        "letter",
        T,
        "Yui Tanaka",
        date(2025, 8, 5),
        23600.00,
        CT.TRAVEL_MEDICAL,
        "Fractured wrist and concussion after a paragliding accident near Interlaken; two nights in hospital.",
        ("no_exclusion",),
    ),
    ClaimSpec(
        "scanned",
        T,
        "Kenji Tanaka",
        date(2025, 9, 14),
        3200.00,
        CT.TRAVEL_CANCELLATION,
        "Trip cancelled because of a sudden illness requiring surgery.",
        ("incident_in_period",),
    ),
    ClaimSpec(
        "form",
        T,
        "Kenji Tanaka",
        date(2025, 6, 20),
        3750.00,
        CT.TRAVEL_CANCELLATION,
        "Trip cancelled two days before departure due to the hospitalisation of an immediate family member.",
    ),
    ClaimSpec(
        "form",
        "DM-TRVL-2024-019",
        "Haruto Sato",
        date(2025, 7, 1),
        900.00,
        CT.TRAVEL_BAGGAGE,
        "Backpack stolen from a hostel locker.",
        ("policy_found",),
    ),
    ClaimSpec(
        "letter",
        T,
        "Yui Tanaka",
        date(2025, 6, 28),
        2950.00,
        CT.TRAVEL_BAGGAGE,
        "Suitcase damaged beyond repair and contents soaked when left on a wet runway apron.",
        ("within_limit",),
    ),
    ClaimSpec(
        "scanned",
        T,
        "Kenji Tanaka",
        date(2025, 7, 30),
        8400.00,
        CT.TRAVEL_MEDICAL,
        "Severe food poisoning in Bangkok requiring two nights of hospital treatment.",
    ),
)


FORM_LABEL_VARIANTS = (
    {
        "policy": "Policy Number",
        "claimant": "Claimant Name",
        "date": "Date of Loss (DD/MM/YYYY)",
        "amount": "Amount Claimed",
        "type": "Type of Claim",
        "desc": "Description of Incident",
        "reported": "Date Reported",
    },
    {
        "policy": "Policy No.",
        "claimant": "Name of Insured Person",
        "date": "Incident Date",
        "amount": "Total Claim Value",
        "type": "Claim Category",
        "desc": "What happened?",
        "reported": "Submission Date",
    },
)


def _fmt_form_date(d: date, variant: int) -> str:
    return d.strftime("%d/%m/%Y") if variant == 0 else d.isoformat()


def _fmt_amount(value: float, style: int) -> str:
    return (f"${value:,.2f}", f"USD {value:,.2f}", f"{value:.2f}")[style % 3]


def _long_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _us_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def build_form_pdf(claim_id: str, spec: ClaimSpec, path: Path, idx: int) -> None:
    variant = idx % 2
    labels = FORM_LABEL_VARIANTS[variant]
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=9, leading=12)
    reported = spec.incident_date + timedelta(days=3 + idx % 5)

    rows = [
        [labels["policy"], spec.policy_number],
        [labels["claimant"], spec.claimant],
        [labels["date"], _fmt_form_date(spec.incident_date, variant)],
        [labels["type"], CLAIM_TYPE_LABELS[spec.claim_type]],
        [labels["amount"], _fmt_amount(spec.amount, idx) if spec.amount is not None else ""],
        [labels["reported"], _fmt_form_date(reported, variant)],
        [labels["desc"], Paragraph(spec.description, small)],
    ]
    table = Table(rows, colWidths=[60 * mm, 105 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
                ("FONT", (1, 0), (1, -1), "Helvetica", 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f3f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story = [
        Paragraph(INSURER, styles["Normal"]),
        Paragraph("Claim Notification Form", styles["Title"]),
        Paragraph(f"Reference: {claim_id}", styles["Normal"]),
        Spacer(1, 8 * mm),
        table,
        Spacer(1, 10 * mm),
        Paragraph(
            "I declare that the information given on this form is true and complete to the best "
            "of my knowledge. Supporting documents are attached.",
            small,
        ),
        Spacer(1, 6 * mm),
        Paragraph(f"Signature: ______________________     Signed on {_fmt_form_date(reported, variant)}", small),
    ]
    SimpleDocTemplate(str(path), pagesize=A4, title=claim_id).build(story)


LETTER_OPENINGS = (
    "My name is {name} and I am writing to make a claim under policy number {policy}. "
    "The incident took place on {date}.",
    "I, {name}, hold cover under policy {policy} and would like to submit a claim for an "
    "incident that happened on {date}.",
    "Please accept this letter as formal notice of a claim. I am {name} (policy ref. {policy}), "
    "and the loss occurred on {date}.",
)


def build_letter_pdf(claim_id: str, spec: ClaimSpec, path: Path, idx: int) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("letter", parent=styles["BodyText"], fontSize=11, leading=16, spaceAfter=10)
    letter_date = spec.incident_date + timedelta(days=6 + idx % 7)
    incident = _long_date(spec.incident_date) if idx % 2 else _us_date(spec.incident_date)
    opening = LETTER_OPENINGS[idx % len(LETTER_OPENINGS)].format(
        name=spec.claimant, policy=spec.policy_number, date=incident
    )
    if spec.amount is None:
        amount_sentence = (
            "I do not yet have the final invoice from the clinic and will forward it as soon as it arrives."
        )
    else:
        amount_sentence = (
            f"The total amount I am claiming is {_fmt_amount(spec.amount, idx + 1)}, as shown on the attached receipts."
        )
    story = [
        Paragraph(_us_date(letter_date), body),
        Paragraph("Claims Department<br/>" + INSURER, body),
        Paragraph(f"Re: {CLAIM_TYPE_LABELS[spec.claim_type]} claim", body),
        Paragraph("Dear Sir or Madam,", body),
        Paragraph(opening, body),
        Paragraph(spec.description, body),
        Paragraph(amount_sentence, body),
        Paragraph(
            "Please let me know if you need anything further. I can be reached at the address on file.",
            body,
        ),
        Paragraph(f"Yours faithfully,<br/><br/>{spec.claimant}", body),
    ]
    SimpleDocTemplate(str(path), pagesize=A4, title=claim_id).build(story)


def degrade_to_scan(pdf_path: Path, rng: random.Random, dpi: int = 200) -> None:
    """Rasterise a PDF and re-save it as an image-only 'scan' with skew and noise."""
    doc = pdfium.PdfDocument(str(pdf_path))
    images: list[Image.Image] = []
    for page in doc:
        img = page.render(scale=dpi / 72).to_pil().convert("L")
        img = img.rotate(rng.uniform(-1.2, 1.2), expand=True, fillcolor=255, resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
        px = img.load()
        w, h = img.size
        for _ in range(w * h // 400):  # speckle noise
            x, y = rng.randrange(w), rng.randrange(h)
            px[x, y] = rng.choice((0, 90, 160))
        images.append(img)
    doc.close()
    images[0].save(pdf_path, "PDF", resolution=dpi, save_all=True, append_images=images[1:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data")
    args = parser.parse_args()

    out: Path = args.out
    for sub in ("policies", "claims", "ground_truth"):
        target = out / sub
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

    for policy in POLICIES:
        build_policy_pdf(policy, out / "policies" / f"{policy.number}.pdf")

    rng = random.Random(42)
    for idx, spec in enumerate(CLAIMS):
        claim_id = f"CLM-2025-{idx + 1:04d}"
        path = out / "claims" / f"{claim_id}.pdf"
        if spec.layout == "letter":
            build_letter_pdf(claim_id, spec, path, idx)
        else:
            build_form_pdf(claim_id, spec, path, idx)
            if spec.layout == "scanned":
                degrade_to_scan(path, rng)

        failed = list(spec.expected_failed_rules)
        truth = {
            "claim_id": claim_id,
            "file": f"claims/{claim_id}.pdf",
            "layout": spec.layout,
            "fields": {
                "policy_number": spec.policy_number,
                "claimant_name": spec.claimant,
                "incident_date": spec.incident_date.isoformat(),
                "amount": spec.amount,
                "claim_type": spec.claim_type.value,
            },
            "expected_failed_rules": failed,
            "expected_route": "needs_review" if failed else "auto_approved",
        }
        (out / "ground_truth" / f"{claim_id}.json").write_text(json.dumps(truth, indent=2) + "\n")

    print(f"Wrote {len(POLICIES)} policies and {len(CLAIMS)} claims to {out}")


if __name__ == "__main__":
    main()
