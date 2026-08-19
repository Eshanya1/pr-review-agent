from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from ..guardrails import UNTRUSTED_CONTENT_NOTICE
from ..observability import trace
from .embeddings import Embedder
from .qa import answer_question
from .vectorstore import VectorStore

JUDGE_SYSTEM_PROMPT = """You are grading whether an answer is faithful to its
source context -- i.e. every factual claim in the answer is actually
supported by the context, with no invented details.

Respond with ONLY a JSON object:
{"faithful": <true|false>, "reason": "<one sentence>"}
"""


class _JudgePayload(BaseModel):
    faithful: bool
    reason: str = Field(default="")


@dataclass
class RetrievalOutcome:
    question: str
    expected_sources: list[str]
    retrieved_sources: list[str]
    hit: bool
    reciprocal_rank: float


@dataclass
class RagEvalReport:
    retrieval: list[RetrievalOutcome] = field(default_factory=list)
    faithfulness: list[dict] = field(default_factory=list)  # only populated in --live mode

    def summary(self) -> dict:
        n = len(self.retrieval)
        hit_rate = sum(o.hit for o in self.retrieval) / n if n else 0.0
        mrr = sum(o.reciprocal_rank for o in self.retrieval) / n if n else 0.0
        out = {
            "questions": n,
            "retrieval_hit_rate": round(hit_rate, 3),
            "retrieval_mrr": round(mrr, 3),
        }
        if self.faithfulness:
            faithful_rate = sum(1 for f in self.faithfulness if f["faithful"]) / len(self.faithfulness)
            out["faithfulness_rate"] = round(faithful_rate, 3)
            out["faithfulness_n"] = len(self.faithfulness)
        return out


def load_questions(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def score_retrieval(question: dict, store: VectorStore, embedder: Embedder, k: int = 5) -> RetrievalOutcome:
    """Free and offline -- only needs the local embedder, no API call.
    hit@k: did any expected source appear in the top-k retrieved chunks.
    Reciprocal rank: 1/rank of the first expected source, 0 if absent."""
    query_vector = embedder.embed([question["question"]])[0]
    results = store.search(query_vector, k=k)
    retrieved_sources = [r.chunk.source for r in results]
    expected = set(question["expected_sources"])

    rr = 0.0
    for i, src in enumerate(retrieved_sources, start=1):
        if src in expected:
            rr = 1.0 / i
            break

    return RetrievalOutcome(
        question=question["question"],
        expected_sources=question["expected_sources"],
        retrieved_sources=retrieved_sources,
        hit=rr > 0,
        reciprocal_rank=rr,
    )


def judge_faithfulness(question: str, answer: str, retrieved: list[dict], model: str) -> dict:
    """LLM-as-judge, hand-rolled rather than pulling in Ragas -- consistent
    with the rest of this project's eval harness (own the metric, don't
    import a black box), and Ragas' default judges assume an OpenAI-shaped
    client anyway."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Faithfulness judging calls the real Claude API; set ANTHROPIC_API_KEY.")

    import anthropic

    context = "\n\n".join(f"[{r['source']}]" for r in retrieved)
    prompt = f"Question: {question}\n\nContext sources used: {context}\n\nAnswer to grade: {answer}"

    client = anthropic.Anthropic()
    with trace("rag_judge", model=model) as usage:
        message = client.messages.create(
            model=model,
            max_tokens=256,
            temperature=0,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": UNTRUSTED_CONTENT_NOTICE + prompt}],
        )
        usage["input_tokens"] = message.usage.input_tokens
        usage["output_tokens"] = message.usage.output_tokens

    text = "".join(b.text for b in message.content if hasattr(b, "text"))
    start, end = text.find("{"), text.rfind("}")
    try:
        payload = _JudgePayload.model_validate(json.loads(text[start : end + 1]))
    except (ValidationError, ValueError):
        return {"faithful": False, "reason": "judge response failed to parse"}
    return {"faithful": payload.faithful, "reason": payload.reason}


def run_rag_eval(
    questions_path: Path, store: VectorStore, embedder: Embedder, live: bool, model: str = "claude-sonnet-4-5", k: int = 5
) -> RagEvalReport:
    report = RagEvalReport()
    for q in load_questions(questions_path):
        outcome = score_retrieval(q, store, embedder, k=k)
        report.retrieval.append(outcome)

        if live:
            result = answer_question(q["question"], store, embedder, model=model, k=k)
            verdict = judge_faithfulness(q["question"], result["answer"], result["retrieved"], model=model)
            report.faithfulness.append({"question": q["question"], **verdict})

    return report
