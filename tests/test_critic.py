from pr_review_agent.critic import decide_escalation, verify_finding
from pr_review_agent.diffparse import AddedLine
from pr_review_agent.findings import Category, Finding, Severity

ADDED = [
    AddedLine(file="app/foo.py", line_no=3, text="    cursor.execute(sql)"),
    AddedLine(file="app/foo.py", line_no=4, text="    return cursor.fetchall()"),
]


def make_finding(evidence, file="app/foo.py", severity=Severity.CRITICAL, confidence=1.0):
    return Finding(
        category=Category.SQL_INJECTION,
        severity=severity,
        file=file,
        line=3,
        summary="test",
        evidence=evidence,
        confidence=confidence,
    )


def test_verify_finding_matches_exact_substring():
    f = verify_finding(make_finding("cursor.execute(sql)"), ADDED)
    assert f.verified is True
    assert f.confidence == 1.0


def test_verify_finding_fails_on_paraphrase():
    f = verify_finding(make_finding("cursor.run(sql_string)"), ADDED)
    assert f.verified is False
    assert f.confidence < 1.0


def test_verify_finding_fails_on_wrong_file():
    f = verify_finding(make_finding("cursor.execute(sql)", file="app/other.py"), ADDED)
    assert f.verified is False
    assert "not touched" in f.verifier_note


def test_decide_escalation_true_for_verified_high_severity():
    f = verify_finding(make_finding("cursor.execute(sql)"), ADDED)
    escalate, reason = decide_escalation([f])
    assert escalate is True
    assert "sql_injection" in reason


def test_decide_escalation_true_for_unverified_high_severity():
    f = verify_finding(make_finding("something not in the diff"), ADDED)
    escalate, reason = decide_escalation([f])
    assert escalate is True
    assert "could not be verified" in reason


def test_decide_escalation_false_for_low_severity():
    f = verify_finding(make_finding("cursor.execute(sql)", severity=Severity.LOW), ADDED)
    escalate, reason = decide_escalation([f])
    assert escalate is False


def test_decide_escalation_false_for_no_findings():
    escalate, reason = decide_escalation([])
    assert escalate is False
    assert reason == ""
