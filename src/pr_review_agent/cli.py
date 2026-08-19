from __future__ import annotations

import json
from pathlib import Path

import click

from .pipeline import build_backend, run_review
from .scoring import build_report, score_fixture

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures"
DEFAULT_CASSETTE_DIR = REPO_ROOT / "eval" / "cassettes"


@click.group()
def main():
    """pr-review-agent: multi-agent PR review with a verifier pass."""


@main.command()
@click.argument("diff_file", type=click.Path(exists=True, path_type=Path))
@click.option("--live", is_flag=True, help="Call the real Claude API instead of cassette replay.")
def review(diff_file: Path, live: bool):
    """Review a single .diff file and print findings as JSON."""
    diff_text = diff_file.read_text()
    if live:
        try:
            backend = build_backend(live=True)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        result = run_review(diff_text, backend)
    else:
        raise click.ClickException(
            "Reviewing an arbitrary diff requires --live and ANTHROPIC_API_KEY "
            "(cassette replay only covers the bundled eval fixtures). "
            "Run `pr-review-agent eval` for the zero-setup demo."
        )
    click.echo(json.dumps(result.to_dict(), indent=2))
    if result.escalate:
        raise SystemExit(1)


@main.command(name="eval")
@click.option("--live", is_flag=True, help="Call the real Claude API instead of cassette replay.")
@click.option("--fixtures-dir", type=click.Path(path_type=Path), default=DEFAULT_FIXTURES_DIR)
@click.option("--cassette-dir", type=click.Path(path_type=Path), default=DEFAULT_CASSETTE_DIR)
@click.option("--json-report", type=click.Path(path_type=Path), default=None, help="Write full report JSON here.")
def eval_cmd(live: bool, fixtures_dir: Path, cassette_dir: Path, json_report: Path | None):
    """Run the bundled eval set and print precision/recall/F1 + escalation accuracy.

    With no flags this needs no API key, no network, and no infra -- it
    replays recorded reviewer outputs (cassettes) against each fixture diff
    and re-runs the real critic/verification/escalation logic on top.
    """
    backend = build_backend(live=live, cassette_dir=cassette_dir)
    fixture_dirs = sorted(p for p in fixtures_dir.iterdir() if p.is_dir())
    if not fixture_dirs:
        raise click.ClickException(f"No fixtures found in {fixtures_dir}")

    outcomes = []
    for fdir in fixture_dirs:
        fixture_id = fdir.name
        diff_text = (fdir / "pr.diff").read_text()
        ground_truth = json.loads((fdir / "ground_truth.json").read_text())

        result = run_review(diff_text, backend, fixture_id=fixture_id)
        outcome = score_fixture(
            fixture_id=fixture_id,
            is_clean=ground_truth["clean"],
            expected_categories=ground_truth.get("categories", []),
            result=result,
            expected_severity=ground_truth.get("severity"),
        )
        outcomes.append(outcome)

        status = "PASS" if (outcome.detected or (outcome.is_clean and not outcome.false_positive)) else "MISS"
        escalate_flag = "OK" if outcome.escalated_correctly else "WRONG"
        click.echo(
            f"[{status}] {fixture_id:32s} clean={outcome.is_clean!s:5} "
            f"findings={len(result.findings):2d} escalate={result.escalate!s:5} ({escalate_flag})"
        )

    report = build_report(outcomes)
    summary = report.summary()
    click.echo("")
    click.echo("=== Eval Summary ===")
    for k, v in summary.items():
        click.echo(f"{k:20s} {v}")

    if json_report:
        json_report.write_text(json.dumps({"summary": summary, "fixtures": [o.fixture_id for o in outcomes]}, indent=2))
        click.echo(f"\nWrote full report to {json_report}")


if __name__ == "__main__":
    main()
