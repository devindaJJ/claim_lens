"""Field-level precision / recall for extraction.

For each field and document:

* **TP** – a value was predicted and it matches the ground truth.
* **FP** – a value was predicted but it is wrong (or the truth is empty).
* **FN** – the truth has a value but the prediction is empty or wrong.

A wrong value therefore counts as both an FP and an FN. Precision answers "when the system
fills in a field, how often is it right?"; recall answers "of the values in the documents,
how many did it get right?".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.normalize import normalize_name, normalize_policy_number


def values_match(name: str, predicted: object | None, truth: object | None) -> bool:
    if predicted is None or truth is None:
        return predicted is None and truth is None
    if name == "amount":
        return abs(float(predicted) - float(truth)) < 0.01
    if name == "claimant_name":
        return normalize_name(str(predicted)) == normalize_name(str(truth))
    if name == "policy_number":
        return normalize_policy_number(str(predicted)) == normalize_policy_number(str(truth))
    return str(predicted) == str(truth)


@dataclass
class FieldScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, name: str, predicted: object | None, truth: object | None) -> bool:
        correct = values_match(name, predicted, truth)
        if predicted is not None and correct:
            self.tp += 1
        elif predicted is None and truth is None:
            self.tn += 1
        else:
            if predicted is not None:
                self.fp += 1
            if truth is not None:
                self.fn += 1
        return correct

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)


@dataclass
class Confusion:
    """Binary confusion for routing: positive = sent to human review."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, predicted_review: bool, truth_review: bool) -> None:
        if predicted_review and truth_review:
            self.tp += 1
        elif predicted_review:
            self.fp += 1
        elif truth_review:
            self.fn += 1
        else:
            self.tn += 1


@dataclass
class EvalSummary:
    fields: dict[str, FieldScore] = field(default_factory=dict)
    by_layout: dict[str, list[int]] = field(default_factory=dict)  # layout -> [correct, total]
    rules_exact: list[int] = field(default_factory=lambda: [0, 0])
    routing: Confusion = field(default_factory=Confusion)
    confident_fields: list[int] = field(default_factory=lambda: [0, 0])  # [correct, total] above threshold
