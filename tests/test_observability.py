import json

from pr_review_agent.observability import estimate_cost_usd, read_traces, summarize, trace


def test_estimate_cost_usd_known_model():
    cost = estimate_cost_usd("claude-sonnet-4-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 18.0  # $3 in + $15 out per million


def test_estimate_cost_usd_unknown_model_uses_default_pricing():
    cost = estimate_cost_usd("some-future-model", input_tokens=1_000_000, output_tokens=0)
    assert cost == 3.0


def test_trace_writes_one_jsonl_line(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    with trace("review", model="claude-sonnet-4-5", trace_file=trace_file) as usage:
        usage["input_tokens"] = 100
        usage["output_tokens"] = 50

    lines = trace_file.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["operation"] == "review"
    assert record["input_tokens"] == 100
    assert record["estimated_cost_usd"] > 0


def test_trace_records_error_and_still_reraises(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    try:
        with trace("review", model="claude-sonnet-4-5", trace_file=trace_file) as usage:
            raise ValueError("boom")
    except ValueError:
        pass

    records = read_traces(trace_file)
    assert records[0]["error"] == "boom"


def test_summarize_aggregates_by_operation(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    for _ in range(2):
        with trace("review", model="claude-sonnet-4-5", trace_file=trace_file) as usage:
            usage["input_tokens"] = 100
            usage["output_tokens"] = 50

    summary = summarize(read_traces(trace_file))
    assert summary["total_calls"] == 2
    assert summary["by_operation"]["review"]["calls"] == 2
