"""RAG audit harness: answer a question set with and without retrieval and report
faithfulness (share of factual sentences supported by a cited passage) and relevance
(retrieval recall@k against expected passages, and answer/reference word overlap)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from mentora.llm.client import LLMClient
from mentora.llm.prompts import PromptRegistry, default_registry
from mentora.rag.grounding import ClaimDetector, EntailmentJudge, check_grounding
from mentora.rag.rerank import RagPipeline
from mentora.rag.retrieve import ScoredPassage
from mentora.rag.text import content_words

Mode = Literal["with_retrieval", "without_retrieval"]


class AuditQuestion(BaseModel):
    id: str
    question: str
    expected_passage_ids: list[str] = Field(default_factory=list)
    reference_answer: str | None = None
    max_week: int | None = None


def load_questions(path: Path) -> list[AuditQuestion]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [AuditQuestion.model_validate(q) for q in raw.get("questions", [])]


@dataclass(frozen=True)
class AuditRow:
    question_id: str
    mode: Mode
    answer: str
    retrieved_ids: list[str]
    recall_at_k: float | None
    faithfulness: float | None
    unsupported_sentences: int
    answer_relevance: float


@dataclass(frozen=True)
class AuditReport:
    rows: list[AuditRow]
    n_questions: int
    target_size: int = 200

    def summary(self) -> dict[str, dict[str, float | None]]:
        out: dict[str, dict[str, float | None]] = {}
        for mode in ("with_retrieval", "without_retrieval"):
            rows = [r for r in self.rows if r.mode == mode]
            faith = [r.faithfulness for r in rows if r.faithfulness is not None]
            recall = [r.recall_at_k for r in rows if r.recall_at_k is not None]
            out[mode] = {
                "faithfulness": round(mean(faith), 3) if faith else None,
                "answer_relevance": round(mean(r.answer_relevance for r in rows), 3)
                if rows
                else None,
                "recall_at_k": round(mean(recall), 3) if recall else None,
                "unsupported_sentences": float(sum(r.unsupported_sentences for r in rows)),
            }
        return out

    def to_json(self) -> str:
        return json.dumps(
            {
                "n_questions": self.n_questions,
                "target_size": self.target_size,
                "summary": self.summary(),
                "rows": [asdict(r) for r in self.rows],
            },
            indent=2,
        )

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            "# RAG audit",
            "",
            f"Questions: {self.n_questions} (target {self.target_size}).",
        ]
        if self.n_questions < self.target_size:
            lines.append(
                "Below the target size: treat these numbers as a smoke test, not a result."
            )
        lines += [
            "",
            "| Mode | Faithfulness | Answer relevance | Recall@k | Unsupported sentences |",
            "|---|---|---|---|---|",
        ]
        for mode, v in s.items():
            cells = [
                "n/a" if v[k] is None else str(v[k])
                for k in ("faithfulness", "answer_relevance", "recall_at_k")
            ]
            unsupported = int(v["unsupported_sentences"] or 0)
            lines.append(f"| {mode} | {' | '.join(cells)} | {unsupported} |")
        return "\n".join(lines) + "\n"


def _overlap(answer: str, target: str) -> float:
    """Share of the target's content words that appear in the answer."""
    t = set(content_words(target))
    return len(t & set(content_words(answer))) / len(t) if t else 0.0


def format_passages(passages: list[ScoredPassage]) -> str:
    return "\n\n".join(f"[{sp.passage.id}] {sp.passage.text}" for sp in passages)


def run_audit(
    questions: list[AuditQuestion],
    pipeline: RagPipeline,
    client: LLMClient,
    judge: EntailmentJudge,
    *,
    course_title: str,
    detector: ClaimDetector | None = None,
    registry: PromptRegistry | None = None,
) -> AuditReport:
    registry = registry or default_registry()
    rows: list[AuditRow] = []
    for q in questions:
        hits = pipeline.search(q.question, max_week=q.max_week)
        ids = [h.passage.id for h in hits]
        texts = {h.passage.id: h.passage.text for h in hits}
        recall = (
            len(set(ids) & set(q.expected_passage_ids)) / len(q.expected_passage_ids)
            if q.expected_passage_ids
            else None
        )
        target = q.reference_answer or q.question
        for mode in ("with_retrieval", "without_retrieval"):
            if mode == "with_retrieval":
                prompt = registry.get("rag/answer").render(
                    course_title=course_title, passages=format_passages(hits), question=q.question
                )
            else:
                prompt = registry.get("rag/answer_no_retrieval").render(
                    course_title=course_title, question=q.question
                )
            answer = client.generate(prompt)
            # Both modes are judged against the same retrieved passages.
            report = check_grounding(answer, texts, judge, detector)
            rows.append(
                AuditRow(
                    question_id=q.id,
                    mode=mode,
                    answer=answer,
                    retrieved_ids=ids if mode == "with_retrieval" else [],
                    recall_at_k=recall if mode == "with_retrieval" else None,
                    faithfulness=report.faithfulness,
                    unsupported_sentences=len(report.failures),
                    answer_relevance=round(_overlap(answer, target), 3),
                )
            )
    return AuditReport(rows, n_questions=len(questions))


@dataclass(frozen=True)
class RetrievalRow:
    question_id: str
    retrieved_ids: list[str]
    recall_at_k: float
    reciprocal_rank: float


def run_retrieval_audit(
    questions: list[AuditQuestion], pipeline: RagPipeline
) -> list[RetrievalRow]:
    """Recall@k and reciprocal rank of the expected passages. Needs no LLM."""
    rows = []
    for q in questions:
        if not q.expected_passage_ids:
            continue
        ids = [h.passage.id for h in pipeline.search(q.question, max_week=q.max_week)]
        expected = set(q.expected_passage_ids)
        first = next((rank for rank, pid in enumerate(ids, 1) if pid in expected), None)
        rows.append(
            RetrievalRow(
                question_id=q.id,
                retrieved_ids=ids,
                recall_at_k=len(set(ids) & expected) / len(expected),
                reciprocal_rank=1 / first if first else 0.0,
            )
        )
    return rows
