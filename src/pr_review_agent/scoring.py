from __future__ import annotations

from dataclasses import dataclass, field

from .findings import ReviewResult


@dataclass
class FixtureOutcome:
    fixture_id: str
    is_clean: bool
    expected_categories: list[str]
    result: ReviewResult
    detected: bool
    false_positive: bool
    escalated_correctly: bool


@dataclass
class EvalReport:
    outcomes: list[FixtureOutcome] = field(default_factory=list)

    @property
    def true_positives(self) -> int:
        return sum(1 for o in self.outcomes if not o.is_clean and o.detected)

    @property
    def false_negatives(self) -> int:
        return sum(1 for o in self.outcomes if not o.is_clean and not o.detected)

    @property
    def false_positives(self) -> int:
        return sum(1 for o in self.outcomes if o.false_positive)

    @property
    def precision(self) -> float:
        tp, fp = self.true_positives, self.false_positives
        return tp / (tp + fp) if (tp + fp) else 0.0

    @property
    def recall(self) -> float:
        tp, fn = self.true_positives, self.false_negatives
        return tp / (tp + fn) if (tp + fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def escalation_accuracy(self) -> float:
        if not self.outcomes:
            return 0.0
        correct = sum(1 for o in self.outcomes if o.escalated_correctly)
        return correct / len(self.outcomes)

    @property
    def auto_approve_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        auto = sum(1 for o in self.outcomes if not o.result.escalate)
        return auto / len(self.outcomes)

    def summary(self) -> dict:
        return {
            "fixtures": len(self.outcomes),
            "true_positives": self.true_positives,
            "false_negatives": self.false_negatives,
            "false_positives": self.false_positives,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "escalation_accuracy": round(self.escalation_accuracy, 3),
            "auto_approve_rate": round(self.auto_approve_rate, 3),
        }


def score_fixture(
    fixture_id: str,
    is_clean: bool,
    expected_categories: list[str],
    result: ReviewResult,
    expected_severity: str | None = None,
) -> FixtureOutcome:
    verified_categories = {f.category.value for f in result.findings if f.verified}
    detected = (not is_clean) and bool(verified_categories & set(expected_categories))

    if is_clean:
        false_positive = len(result.findings) > 0
    else:
        false_positive = bool(result.findings) and not (verified_categories & set(expected_categories))

    # Only high/critical bugs are worth pulling a human into the loop for;
    # low/medium findings should be auto-resolved (e.g. left as a comment).
    should_escalate = (not is_clean) and expected_severity in ("high", "critical")
    escalated_correctly = result.escalate == should_escalate

    return FixtureOutcome(
        fixture_id=fixture_id,
        is_clean=is_clean,
        expected_categories=expected_categories,
        result=result,
        detected=detected,
        false_positive=false_positive,
        escalated_correctly=escalated_correctly,
    )


def build_report(outcomes: list[FixtureOutcome]) -> EvalReport:
    return EvalReport(outcomes=outcomes)
