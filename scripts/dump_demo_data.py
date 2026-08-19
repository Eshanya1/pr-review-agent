#!/usr/bin/env python3
"""Dumps a single JSON blob (cassette + live results, scored) for the static
in-browser demo artifact. Run with ANTHROPIC_API_KEY set to include a fresh
live snapshot; without it, live_findings will be null per fixture.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures"

import sys
sys.path.insert(0, str(REPO_ROOT / "src"))

from pr_review_agent.pipeline import build_backend, run_review  # noqa: E402
from pr_review_agent.scoring import build_report, score_fixture  # noqa: E402


def dump(backend, live: bool):
    outcomes = []
    per_fixture = []
    for fdir in sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir()):
        fid = fdir.name
        diff_text = (fdir / "pr.diff").read_text()
        gt = json.loads((fdir / "ground_truth.json").read_text())
        result = run_review(diff_text, backend, fixture_id=fid)
        outcome = score_fixture(fid, gt["clean"], gt.get("categories", []), result, gt.get("severity"))
        outcomes.append(outcome)
        per_fixture.append({
            "id": fid,
            "file": diff_text.splitlines()[4].removeprefix("+++ b/"),
            "diff": diff_text,
            "ground_truth": gt,
            "findings": result.to_dict()["findings"],
            "escalate": result.escalate,
            "escalation_reason": result.escalation_reason,
            "detected": outcome.detected,
            "false_positive": outcome.false_positive,
            "escalated_correctly": outcome.escalated_correctly,
        })
    report = build_report(outcomes)
    return {"summary": report.summary(), "fixtures": per_fixture}


def main():
    cassette_backend = build_backend(live=False)
    data = {"cassette": dump(cassette_backend, live=False)}

    if os.environ.get("ANTHROPIC_API_KEY"):
        live_backend = build_backend(live=True)
        data["live"] = dump(live_backend, live=True)
    else:
        data["live"] = None
        print("ANTHROPIC_API_KEY not set -- skipping live dump", file=sys.stderr)

    out_path = Path("/tmp/demo_data.json")
    out_path.write_text(json.dumps(data, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
