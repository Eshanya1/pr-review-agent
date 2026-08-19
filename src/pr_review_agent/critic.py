from __future__ import annotations

from .diffparse import AddedLine
from .findings import Finding, Severity

ESCALATION_SEVERITIES = {Severity.HIGH, Severity.CRITICAL}
ESCALATION_CONFIDENCE_FLOOR = 0.6


def verify_finding(finding: Finding, added_lines: list[AddedLine]) -> Finding:
    """Cross-checks a finding's evidence against the actual diff.

    A finding is only "verified" if its file matches a touched file AND its
    evidence string is a literal substring of a line that diff really adds.
    Unverified findings are not discarded outright (they may still be a real
    but loosely-quoted issue) but their confidence is cut, which pulls them
    below the auto-approve threshold and routes the PR to a human instead.
    """
    same_file_lines = [al for al in added_lines if al.file == finding.file]
    match = any(finding.evidence.strip() in al.text for al in same_file_lines)

    if match:
        finding.verified = True
        finding.verifier_note = "evidence located in diff"
    else:
        finding.verified = False
        finding.confidence = round(finding.confidence * 0.3, 3)
        if not same_file_lines:
            finding.verifier_note = f"file '{finding.file}' not touched by this diff"
        else:
            finding.verifier_note = "evidence string not found in added lines"
    return finding


def review_and_verify(findings: list[Finding], added_lines: list[AddedLine]) -> list[Finding]:
    return [verify_finding(f, added_lines) for f in findings]


def decide_escalation(findings: list[Finding]) -> tuple[bool, str]:
    """Human-in-the-loop policy: auto-approve unless a high-confidence,
    high-severity finding survives critic verification."""
    risky = [
        f
        for f in findings
        if f.severity in ESCALATION_SEVERITIES and f.confidence >= ESCALATION_CONFIDENCE_FLOOR
    ]
    if risky:
        worst = max(risky, key=lambda f: (f.severity.rank, f.confidence))
        return True, f"{worst.severity.value} severity {worst.category.value} finding at {worst.file}:{worst.line}"

    unverified_risky = [f for f in findings if f.severity in ESCALATION_SEVERITIES and not f.verified]
    if unverified_risky:
        return True, "high-severity finding could not be verified against the diff; needs human judgment"

    return False, ""
