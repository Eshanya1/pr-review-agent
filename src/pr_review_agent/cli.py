from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

import click

from .pipeline import build_backend, run_review
from .scoring import build_report, score_fixture

_EVAL_DATA = importlib.resources.files("pr_review_agent") / "eval_data"
DEFAULT_FIXTURES_DIR = Path(str(_EVAL_DATA / "fixtures"))
DEFAULT_CASSETTE_DIR = Path(str(_EVAL_DATA / "cassettes"))


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
            result = run_review(diff_text, backend)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:  # anthropic.APIError and friends
            raise click.ClickException(f"Claude API call failed: {exc}") from exc
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
    try:
        backend = build_backend(live=live, cassette_dir=cassette_dir)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    fixture_dirs = sorted(p for p in fixtures_dir.iterdir() if p.is_dir())
    if not fixture_dirs:
        raise click.ClickException(f"No fixtures found in {fixtures_dir}")

    outcomes = []
    for fdir in fixture_dirs:
        fixture_id = fdir.name
        diff_text = (fdir / "pr.diff").read_text()
        ground_truth = json.loads((fdir / "ground_truth.json").read_text())

        try:
            result = run_review(diff_text, backend, fixture_id=fixture_id)
        except Exception as exc:  # anthropic.APIError and friends
            raise click.ClickException(f"Claude API call failed on fixture '{fixture_id}': {exc}") from exc
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


@main.group()
def rag():
    """Index a repo and ask natural-language questions about it."""


@rag.command(name="index")
@click.option("--path", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path("."), show_default=True)
@click.option("--index-dir", type=click.Path(path_type=Path), default=None, help="Defaults to <path>/.rag_index")
def rag_index(path: Path, index_dir: Path | None):
    """Chunk + embed a repo's code, docs, and commit history into a local vector store."""
    from .rag.chunking import ingest_repo
    from .rag.embeddings import LocalEmbedder
    from .rag.vectorstore import VectorStore

    index_dir = index_dir or (path / ".rag_index")
    click.echo(f"Ingesting {path}...")
    chunks = ingest_repo(path)
    if not chunks:
        raise click.ClickException(f"No indexable files found under {path}")
    click.echo(f"{len(chunks)} chunks. Embedding locally (first run downloads a small model, ~90MB)...")
    try:
        embedder = LocalEmbedder()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    vectors = embedder.embed([c.text for c in chunks])

    store = VectorStore()
    store.build(chunks, vectors)
    store.save(index_dir)
    click.echo(f"Indexed {len(chunks)} chunks -> {index_dir}")


@rag.command(name="ask")
@click.argument("question")
@click.option("--index-dir", type=click.Path(path_type=Path), default=Path(".rag_index"), show_default=True)
@click.option("--k", default=5, show_default=True, help="Number of chunks to retrieve.")
def rag_ask(question: str, index_dir: Path, k: int):
    """Ask a natural-language question about an indexed repo. Calls the real Claude API."""
    from .rag.embeddings import LocalEmbedder
    from .rag.qa import answer_question
    from .rag.vectorstore import VectorStore

    if not VectorStore.exists(index_dir):
        raise click.ClickException(f"No index found at {index_dir}. Run `pr-review-agent rag index` first.")

    store = VectorStore.load(index_dir)
    try:
        embedder = LocalEmbedder()
        result = answer_question(question, store, embedder, k=k)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:  # anthropic.APIError and friends
        raise click.ClickException(f"Claude API call failed: {exc}") from exc

    click.echo(json.dumps(result, indent=2))


@rag.command(name="eval")
@click.option("--index-dir", type=click.Path(path_type=Path), default=Path(".rag_index"), show_default=True)
@click.option(
    "--questions-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Defaults to the bundled eval_data/rag_questions.json",
)
@click.option("--live", is_flag=True, help="Also generate real answers and LLM-judge their faithfulness (calls Claude API).")
@click.option("--k", default=5, show_default=True)
def rag_eval_cmd(index_dir: Path, questions_file: Path | None, live: bool, k: int):
    """Score retrieval quality (free, offline) and optionally answer faithfulness (--live).

    Retrieval scoring only needs the local embedder -- hit-rate and MRR
    against a hand-labeled question set cost nothing and need no API key.
    --live additionally generates real answers and has Claude judge whether
    each one is actually grounded in what was retrieved.
    """
    from .rag.embeddings import LocalEmbedder
    from .rag.eval_rag import run_rag_eval
    from .rag.vectorstore import VectorStore

    if not VectorStore.exists(index_dir):
        raise click.ClickException(f"No index found at {index_dir}. Run `pr-review-agent rag index` first.")

    questions_file = questions_file or Path(str(_EVAL_DATA / "rag_questions.json"))
    store = VectorStore.load(index_dir)
    embedder = LocalEmbedder()

    try:
        report = run_rag_eval(questions_file, store, embedder, live=live, k=k)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:  # anthropic.APIError and friends
        raise click.ClickException(f"Claude API call failed: {exc}") from exc

    for o in report.retrieval:
        status = "HIT" if o.hit else "MISS"
        click.echo(f"[{status}] {o.question[:60]:60s} expected={o.expected_sources}")

    if live:
        click.echo("")
        for f in report.faithfulness:
            status = "FAITHFUL" if f["faithful"] else "UNFAITHFUL"
            click.echo(f"[{status}] {f['question'][:60]:60s} {f['reason']}")

    click.echo("")
    click.echo("=== RAG Eval Summary ===")
    for k_, v in report.summary().items():
        click.echo(f"{k_:22s} {v}")


@main.command()
def stats():
    """Summarize local observability traces from past review/rag-ask calls.

    Self-built and local (~/.pr-review-agent/traces.jsonl) -- no external
    account, no network call needed to see cost/latency history.
    """
    from .observability import TRACE_FILE, read_traces, summarize

    records = read_traces()
    if not records:
        click.echo(f"No traces recorded yet at {TRACE_FILE}.")
        return

    summary = summarize(records)
    click.echo(f"=== Stats: {summary['total_calls']} calls, {summary['total_errors']} errors, ~${summary['total_estimated_cost_usd']} total ===")
    click.echo("")
    for op, b in summary["by_operation"].items():
        click.echo(
            f"{op:12s} calls={b['calls']:4d} errors={b['errors']:3d} "
            f"avg_latency={b['avg_latency_ms']:7.1f}ms  ~${b['total_cost_usd']}"
        )


if __name__ == "__main__":
    main()
