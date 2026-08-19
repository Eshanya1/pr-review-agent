from __future__ import annotations

import importlib.resources
from pathlib import Path

from .critic import decide_escalation, review_and_verify
from .diffparse import parse_added_lines
from .findings import ReviewResult
from .guardrails import scan_for_injection
from .reviewer import AnthropicBackend, CassetteBackend, ReviewerBackend

# Resolved via importlib.resources, not a path relative to this file, so it
# works whether the package is installed editable (dev checkout) or as a
# regular wheel (e.g. Binder) -- eval_data is shipped as package data either way.
DEFAULT_CASSETTE_DIR = Path(str(importlib.resources.files("pr_review_agent") / "eval_data" / "cassettes"))


def build_backend(live: bool, cassette_dir: Path | None = None) -> ReviewerBackend:
    if live:
        return AnthropicBackend()
    return CassetteBackend(cassette_dir or DEFAULT_CASSETTE_DIR)


def run_review(diff_text: str, backend: ReviewerBackend, fixture_id: str | None = None) -> ReviewResult:
    flagged = scan_for_injection(diff_text)
    raw_findings = backend.review(diff_text, fixture_id=fixture_id)
    added_lines = parse_added_lines(diff_text)
    verified = review_and_verify(raw_findings, added_lines)
    escalate, reason = decide_escalation(verified)

    if flagged and not escalate:
        # A diff that itself tries to talk to the reviewer ("ignore your
        # instructions...") is suspicious regardless of what findings came
        # back -- don't let a clean-looking result auto-approve it.
        escalate, reason = True, "diff content matched a prompt-injection pattern; needs human review"

    return ReviewResult(findings=verified, escalate=escalate, escalation_reason=reason, input_flagged=flagged)
