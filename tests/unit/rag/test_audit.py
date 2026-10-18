from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from mentora.llm.backends.fake import FakeLLM
from mentora.llm.client import LLMClient
from mentora.llm.types import LLMRequest
from mentora.rag.audit import AuditQuestion, load_questions, run_audit, run_retrieval_audit
from mentora.rag.embeddings import HashingEmbedder
from mentora.rag.grounding import LexicalEntailmentJudge
from mentora.rag.rerank import LexicalReranker, RagPipeline
from mentora.rag.retrieve import HybridRetriever

ROOT = Path(__file__).resolve().parents[3]


def _grounded_answer(req: LLMRequest) -> str:
    """Fake tutor: repeat the first sentence of the top passage, with its citation."""
    match = re.search(r"^\[([^\]]+)\] (.+?\.)(?:\s|$)", req.messages[-1].content, re.MULTILINE)
    assert match, "rag/answer prompt must list passages as [id] text"
    return f"{match.group(2)} [{match.group(1)}]"


def test_audit_compares_with_and_without_retrieval(
    session_factory: sessionmaker[Session], ingested: int, embedder: HashingEmbedder
) -> None:
    pipeline = RagPipeline(
        HybridRetriever.from_db(session_factory, ingested, embedder, beta=0.4, top_k=20),
        LexicalReranker(),
        top_k=4,
    )
    fake = FakeLLM(
        {
            "rag/answer": _grounded_answer,
            "rag/answer_no_retrieval": "Python was designed in 1850 by a committee of snakes.",
        }
    )
    questions = load_questions(ROOT / "data" / "sample" / "rag_audit_questions.yaml")
    assert len(questions) == 12
    report = run_audit(
        questions,
        pipeline,
        LLMClient(fake),
        LexicalEntailmentJudge(0.6),
        course_title="Intro",
    )
    summary = report.summary()
    assert summary["with_retrieval"]["faithfulness"] == 1.0
    assert summary["without_retrieval"]["faithfulness"] == 0.0
    assert len(report.rows) == 24
    assert "Below the target size" in report.to_markdown()
    assert json.loads(report.to_json())["n_questions"] == 12


def test_recall_uses_expected_passages(
    session_factory: sessionmaker[Session], ingested: int, embedder: HashingEmbedder
) -> None:
    pipeline = RagPipeline(
        HybridRetriever.from_db(session_factory, ingested, embedder, beta=0.4, top_k=20),
        LexicalReranker(),
        top_k=4,
    )
    top = pipeline.search("Does range(10) include 10?")[0].passage.id
    q = AuditQuestion(
        id="r", question="Does range(10) include 10?", expected_passage_ids=[top, "missing-id"]
    )
    report = run_audit(
        [q], pipeline, LLMClient(FakeLLM()), LexicalEntailmentJudge(0.6), course_title="c"
    )
    assert report.summary()["with_retrieval"]["recall_at_k"] == 0.5


def test_retrieval_only_audit_needs_no_llm(
    session_factory: sessionmaker[Session], ingested: int, embedder: HashingEmbedder
) -> None:
    pipeline = RagPipeline(
        HybridRetriever.from_db(session_factory, ingested, embedder, beta=0.4, top_k=20),
        LexicalReranker(),
        top_k=4,
    )
    questions = load_questions(ROOT / "data" / "sample" / "rag_audit_questions.yaml")
    rows = run_retrieval_audit(questions, pipeline)
    assert len(rows) == 12
    assert all(0.0 <= r.recall_at_k <= 1.0 and 0.0 <= r.reciprocal_rank <= 1.0 for r in rows)
    # The expected ids in the sample file must exist in the ingested corpus.
    known = {p.id for p in pipeline.retriever.passages}
    assert {pid for q in questions for pid in q.expected_passage_ids} <= known
