from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .findings import Finding

SYSTEM_PROMPT = """You are a senior application security and correctness reviewer.
You will be given a unified diff of a pull request. Find real bugs the diff
introduces: security vulnerabilities (injection, insecure deserialization,
missing auth, secrets/PII exposure, shell injection, etc.) and correctness
bugs (off-by-one errors, race conditions, timezone handling, session/expiry
logic, etc.).

Rules:
- Only report issues caused by lines the diff ADDS (lines starting with '+').
- Every finding's "evidence" field must be an exact substring of an added
  line, quoted verbatim, so it can be mechanically verified against the diff.
- Do not invent files, line numbers, or code that is not in the diff.
- If the diff looks correct and safe, return an empty findings list. Do not
  manufacture issues to have something to report.

Respond with ONLY a JSON object of the form:
{"findings": [
  {"category": "<one of: sql_injection, insecure_deserialization, pii_logging,
    off_by_one, missing_auth, timezone_bug, shell_injection, session_expiry,
    race_condition, other>",
   "severity": "<low|medium|high|critical>",
   "file": "<path from the diff>",
   "line": <int, target line number>,
   "summary": "<one sentence, specific to this diff>",
   "evidence": "<exact substring of the added line>"}
]}
"""


class ReviewerBackend(Protocol):
    def review(self, diff_text: str, fixture_id: str | None = None) -> list[Finding]: ...


class CassetteBackend:
    """Replays a pre-recorded reviewer response for a known fixture.

    This is what powers the zero-setup demo (`pr-review-agent eval`, no flags):
    no API key, no network call, fully deterministic. Cassettes live in
    eval/cassettes/<fixture_id>.json and were recorded from real review runs.
    """

    def __init__(self, cassette_dir: Path):
        self.cassette_dir = Path(cassette_dir)

    def review(self, diff_text: str, fixture_id: str | None = None) -> list[Finding]:
        if fixture_id is None:
            raise ValueError(
                "CassetteBackend can only replay known fixtures; pass fixture_id "
                "or use --live with ANTHROPIC_API_KEY set for arbitrary diffs."
            )
        cassette_path = self.cassette_dir / f"{fixture_id}.json"
        if not cassette_path.exists():
            raise FileNotFoundError(f"No cassette recorded for fixture '{fixture_id}' at {cassette_path}")
        data = json.loads(cassette_path.read_text())
        return [Finding.from_dict(f) for f in data["findings"]]


class AnthropicBackend:
    """Calls the real Claude API. Requires ANTHROPIC_API_KEY."""

    def __init__(self, model: str = "claude-sonnet-4-5"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it to use --live review, or "
                "omit --live to run the offline cassette-backed demo instead."
            )
        import anthropic  # imported lazily so the package works with zero deps installed offline

        self.model = model
        self.client = anthropic.Anthropic()

    def review(self, diff_text: str, fixture_id: str | None = None) -> list[Finding]:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=0,  # reviewer output should be reproducible, not creative
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Review this diff:\n\n{diff_text}"}],
        )
        text = "".join(block.text for block in message.content if hasattr(block, "text"))
        payload = _extract_json(text)
        return [Finding.from_dict(f) for f in payload.get("findings", [])]


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"findings": []}
    return json.loads(text[start : end + 1])
