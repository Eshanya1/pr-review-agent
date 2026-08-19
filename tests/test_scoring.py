from pr_review_agent.findings import Category, Finding, ReviewResult, Severity
from pr_review_agent.scoring import build_report, score_fixture


def verified_finding(category=Category.SQL_INJECTION, severity=Severity.CRITICAL):
    return Finding(
        category=category,
        severity=severity,
        file="a.py",
        line=1,
        summary="s",
        evidence="e",
        verified=True,
    )


def test_score_fixture_true_positive():
    result = ReviewResult(findings=[verified_finding()], escalate=True)
    o = score_fixture("f1", is_clean=False, expected_categories=["sql_injection"], result=result, expected_severity="critical")
    assert o.detected is True
    assert o.false_positive is False
    assert o.escalated_correctly is True


def test_score_fixture_false_negative():
    result = ReviewResult(findings=[], escalate=False)
    o = score_fixture("f2", is_clean=False, expected_categories=["sql_injection"], result=result, expected_severity="critical")
    assert o.detected is False
    assert o.escalated_correctly is False  # should have escalated a critical bug but didn't


def test_score_fixture_false_positive_on_clean():
    result = ReviewResult(findings=[verified_finding()], escalate=False)
    o = score_fixture("f3", is_clean=True, expected_categories=[], result=result, expected_severity=None)
    assert o.false_positive is True
    assert o.detected is False


def test_score_fixture_low_severity_bug_should_not_escalate():
    result = ReviewResult(findings=[verified_finding(severity=Severity.LOW)], escalate=False)
    o = score_fixture("f4", is_clean=False, expected_categories=["sql_injection"], result=result, expected_severity="low")
    assert o.detected is True
    assert o.escalated_correctly is True  # correctly did NOT escalate a low-severity bug


def test_eval_report_precision_recall_f1():
    tp = score_fixture("tp", False, ["sql_injection"], ReviewResult(findings=[verified_finding()]), "critical")
    fn = score_fixture("fn", False, ["sql_injection"], ReviewResult(findings=[]), "critical")
    fp = score_fixture("fp", True, [], ReviewResult(findings=[verified_finding()]), None)
    tn = score_fixture("tn", True, [], ReviewResult(findings=[]), None)

    report = build_report([tp, fn, fp, tn])
    assert report.true_positives == 1
    assert report.false_negatives == 1
    assert report.false_positives == 1
    assert report.precision == 0.5
    assert report.recall == 0.5
    assert round(report.f1, 3) == 0.5


def test_eval_report_handles_empty():
    report = build_report([])
    assert report.precision == 0.0
    assert report.recall == 0.0
    assert report.f1 == 0.0
