from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TRACE_DIR = Path.home() / ".pr-review-agent"
TRACE_FILE = TRACE_DIR / "traces.jsonl"

# $ per million tokens (input, output). Approximate, for cost *estimation*
# only -- not pulled from a pricing API, so treat as directional, not a bill.
PRICING_PER_MILLION = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
}
DEFAULT_PRICING = (3.00, 15.00)  # assume Sonnet-class pricing for unknown models


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICING_PER_MILLION.get(model, DEFAULT_PRICING)
    return round((input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price, 6)


@contextmanager
def trace(operation: str, model: str | None = None, trace_file: Path = TRACE_FILE):
    """Wrap an LLM call; the caller fills in usage['input_tokens'] /
    usage['output_tokens'] from the API response before the block exits.

    Self-built rather than wired to LangSmith so this needs no external
    account or network call -- consistent with the rest of the project's
    zero-setup default. Every call appends one line to ~/.pr-review-agent/
    traces.jsonl; `pr-review-agent stats` summarizes them.
    """
    start = time.monotonic()
    usage: dict = {}
    error: str | None = None
    try:
        yield usage
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "model": model,
            "latency_ms": latency_ms,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "error": error,
        }
        if model and usage.get("input_tokens") is not None:
            record["estimated_cost_usd"] = estimate_cost_usd(
                model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            )
        _append(record, trace_file)


def _append(record: dict, trace_file: Path = TRACE_FILE) -> None:
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    with trace_file.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_traces(trace_file: Path = TRACE_FILE) -> list[dict]:
    if not trace_file.exists():
        return []
    records = []
    for line in trace_file.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def summarize(records: list[dict]) -> dict:
    by_op: dict[str, dict] = {}
    total_cost = 0.0
    total_calls = 0
    total_errors = 0
    for r in records:
        op = r["operation"]
        bucket = by_op.setdefault(op, {"calls": 0, "errors": 0, "total_latency_ms": 0.0, "total_cost_usd": 0.0})
        bucket["calls"] += 1
        total_calls += 1
        if r.get("error"):
            bucket["errors"] += 1
            total_errors += 1
        bucket["total_latency_ms"] += r.get("latency_ms") or 0
        cost = r.get("estimated_cost_usd") or 0
        bucket["total_cost_usd"] += cost
        total_cost += cost

    for bucket in by_op.values():
        bucket["avg_latency_ms"] = round(bucket["total_latency_ms"] / bucket["calls"], 1) if bucket["calls"] else 0
        bucket["total_cost_usd"] = round(bucket["total_cost_usd"], 4)
        del bucket["total_latency_ms"]

    return {
        "total_calls": total_calls,
        "total_errors": total_errors,
        "total_estimated_cost_usd": round(total_cost, 4),
        "by_operation": by_op,
    }
