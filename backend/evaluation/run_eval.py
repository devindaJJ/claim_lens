"""Evaluate extraction, rule validation and routing against the ground-truth set.

    python -m evaluation.run_eval --extractor heuristic
    python -m evaluation.run_eval --extractor claude --update-readme

Runs the full pipeline (text/OCR → extraction → retrieval → rules → routing) in-process,
using an in-memory vector index over the policy PDFs, so no database or worker is needed.
Per-extractor results are written to ``evaluation/results/<extractor>.json`` and a Markdown
report combining every available result file to ``evaluation/results/report.md``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import REPO_ROOT, get_settings
from app.schemas.domain import CLAIM_FIELDS, Route
from app.services.pipeline import Pipeline
from app.services.rag.retriever import InMemoryRetriever
from evaluation.metrics import EvalSummary, FieldScore

RESULTS_DIR = Path(__file__).resolve().parent / "results"
README = REPO_ROOT / "README.md"
START, END = "<!-- EVAL:START -->", "<!-- EVAL:END -->"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def _prediction(claim, name: str):
    value = getattr(claim, name)
    if value is None:
        return None
    if name == "incident_date":
        return value.isoformat()
    if name == "claim_type":
        return value.value
    return value


def evaluate(extractor: str, data_dir: Path) -> dict:
    settings = get_settings()
    retriever = InMemoryRetriever.from_directory(data_dir / "policies")
    pipeline = Pipeline.create(settings, retriever, extractor)
    summary = EvalSummary(fields={name: FieldScore() for name in CLAIM_FIELDS})
    rows = []
    started = time.perf_counter()

    for truth_path in sorted((data_dir / "ground_truth").glob("*.json")):
        truth = json.loads(truth_path.read_text())
        result = pipeline.run(data_dir / truth["file"])
        claim, metas = result.extraction.claim, result.extraction.fields

        field_rows = {}
        for name in CLAIM_FIELDS:
            predicted = _prediction(claim, name)
            correct = summary.fields[name].add(name, predicted, truth["fields"][name])
            layout = summary.by_layout.setdefault(truth["layout"], [0, 0])
            layout[0] += correct
            layout[1] += 1
            if metas[name].confidence >= settings.confidence_threshold:
                summary.confident_fields[0] += correct
                summary.confident_fields[1] += 1
            field_rows[name] = {
                "predicted": predicted,
                "truth": truth["fields"][name],
                "correct": correct,
                "confidence": metas[name].confidence,
            }

        failed = sorted(r.code.value for r in result.rules if not r.passed)
        expected_failed = sorted(truth["expected_failed_rules"])
        summary.rules_exact[0] += failed == expected_failed
        summary.rules_exact[1] += 1
        predicted_review = result.routing.route == Route.NEEDS_REVIEW
        summary.routing.add(predicted_review, truth["expected_route"] == Route.NEEDS_REVIEW.value)

        rows.append(
            {
                "claim_id": truth["claim_id"],
                "layout": truth["layout"],
                "text_method": result.document.method,
                "fields": field_rows,
                "failed_rules": failed,
                "expected_failed_rules": expected_failed,
                "route": result.routing.route.value,
                "expected_route": truth["expected_route"],
            }
        )
        marks = "".join("✓" if f["correct"] else "✗" for f in field_rows.values())
        print(
            f"  {truth['claim_id']}  {truth['layout']:<8} fields {marks}  rules {'✓' if failed == expected_failed else '✗'}  {result.routing.route.value}"
        )

    r = summary.routing
    return {
        "extractor": extractor,
        "model": settings.anthropic_model if extractor == "claude" else None,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": len(rows),
        "seconds": round(time.perf_counter() - started, 1),
        "confidence_threshold": settings.confidence_threshold,
        "fields": {
            name: {
                "tp": s.tp,
                "fp": s.fp,
                "fn": s.fn,
                "tn": s.tn,
                "precision": s.precision,
                "recall": s.recall,
                "f1": s.f1,
            }
            for name, s in summary.fields.items()
        },
        "by_layout": {k: {"correct": c, "total": t} for k, (c, t) in sorted(summary.by_layout.items())},
        "rules_exact_match": summary.rules_exact[0] / summary.rules_exact[1],
        "routing": {
            "tp": r.tp,
            "fp": r.fp,
            "fn": r.fn,
            "tn": r.tn,
            "review_recall": r.tp / (r.tp + r.fn) if r.tp + r.fn else None,
            "unsafe_auto_approvals": r.fn,
            "unnecessary_reviews": r.fp,
        },
        "confident_field_accuracy": (
            summary.confident_fields[0] / summary.confident_fields[1] if summary.confident_fields[1] else None
        ),
        "confident_field_share": summary.confident_fields[1] / (len(rows) * len(CLAIM_FIELDS)),
        "claims": rows,
    }


def render_report(results: list[dict]) -> str:
    names = [r["extractor"] for r in results]
    header = "| Field | " + " | ".join(f"{n} P | {n} R" for n in names) + " |"
    sep = "|---|" + "---:|---:|" * len(names)
    lines = [
        f"Evaluated on {results[0]['documents']} synthetic claims "
        f"({', '.join(f'{k}: {v["total"] // len(CLAIM_FIELDS)}' for k, v in results[0]['by_layout'].items())}). "
        "P = precision, R = recall.",
        "",
        header,
        sep,
    ]
    for name in CLAIM_FIELDS:
        cells = " | ".join(
            f"{_pct(r['fields'][name]['precision'])} | {_pct(r['fields'][name]['recall'])}" for r in results
        )
        lines.append(f"| `{name}` | {cells} |")

    lines += ["", "| Metric | " + " | ".join(names) + " |", "|---|" + "---:|" * len(names)]

    def row(label: str, fn) -> None:
        lines.append(f"| {label} | " + " | ".join(fn(r) for r in results) + " |")

    for layout in results[0]["by_layout"]:
        row(
            f"Field accuracy – {layout}",
            lambda r, k=layout: _pct(r["by_layout"][k]["correct"] / r["by_layout"][k]["total"]),
        )
    row("Rule outcomes exactly right (per claim)", lambda r: _pct(r["rules_exact_match"]))
    row("Claims needing review that were sent to review", lambda r: _pct(r["routing"]["review_recall"]))
    row("Unsafe auto-approvals", lambda r: str(r["routing"]["unsafe_auto_approvals"]))
    row("Unnecessary reviews", lambda r: str(r["routing"]["unnecessary_reviews"]))
    row(
        f"Accuracy of fields with confidence ≥ {results[0]['confidence_threshold']}",
        lambda r: _pct(r["confident_field_accuracy"]),
    )
    row("Share of fields above the threshold", lambda r: _pct(r["confident_field_share"]))
    lines += [
        "",
        "Run details: "
        + "; ".join(
            f"{r['extractor']}{' (' + r['model'] + ')' if r['model'] else ''} – {r['generated_at']}, {r['seconds']}s"
            for r in results
        )
        + ".",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=["heuristic", "claude"], default="heuristic")
    parser.add_argument("--data", type=Path, default=get_settings().data_dir)
    parser.add_argument("--update-readme", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    print(f"Evaluating extractor={args.extractor} on {args.data}")
    result = evaluate(args.extractor, args.data)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{args.extractor}.json").write_text(json.dumps(result, indent=2) + "\n")

    order = {"claude": 0, "heuristic": 1}
    results = sorted(
        (json.loads(p.read_text()) for p in RESULTS_DIR.glob("*.json")),
        key=lambda r: order.get(r["extractor"], 9),
    )
    report = render_report(results)
    (RESULTS_DIR / "report.md").write_text(report + "\n")
    print("\n" + report)

    if args.update_readme:
        text = README.read_text()
        if START not in text or END not in text:
            sys.exit(f"README is missing the {START} / {END} markers")
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        README.write_text(f"{head}{START}\n{report}\n{END}{tail}")
        print(f"\nUpdated {README}")


if __name__ == "__main__":
    main()
