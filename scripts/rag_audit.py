"""Run the RAG audit and write JSON + Markdown reports.

Full audit (calls the configured LLM: with vs without retrieval):
    python scripts/rag_audit.py --questions data/sample/rag_audit_questions.yaml --out reports/

Retrieval only (no LLM, no cost): recall@k and MRR against expected passage ids:
    python scripts/rag_audit.py --retrieval-only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from sqlalchemy import select

from mentora.config import get_settings
from mentora.course import load_course
from mentora.db import make_engine, make_session_factory
from mentora.db import models as m
from mentora.llm import make_client
from mentora.rag import build_pipeline
from mentora.rag.audit import load_questions, run_audit, run_retrieval_audit
from mentora.rag.grounding import make_judge


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=Path("data/sample/rag_audit_questions.yaml"))
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--retrieval-only", action="store_true")
    args = ap.parse_args()

    factory = make_session_factory(make_engine())
    course = load_course(settings.app.concepts_file)
    with factory() as db:
        course_id = db.scalars(select(m.Course.id).where(m.Course.code == course.code)).one()
    pipeline = build_pipeline(settings, factory, course_id)
    questions = load_questions(args.questions)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.retrieval_only:
        rows = run_retrieval_audit(questions, pipeline)
        recall = mean(r.recall_at_k for r in rows) if rows else 0.0
        mrr = mean(r.reciprocal_rank for r in rows) if rows else 0.0
        summary = {
            "questions": len(rows),
            f"recall_at_{settings.rag.top_k_rerank}": round(recall, 3),
            "mrr": round(mrr, 3),
        }
        payload = {"summary": summary, "rows": [asdict(r) for r in rows]}
        (args.out / "rag_retrieval_audit.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2))
        for r in rows:
            if r.recall_at_k < 1:
                print(f"  missed: {r.question_id} recall={r.recall_at_k:.2f} got {r.retrieved_ids}")
        return

    client = make_client(settings)
    report = run_audit(
        questions, pipeline, client, make_judge(settings, client), course_title=course.title
    )
    (args.out / "rag_audit.json").write_text(report.to_json(), encoding="utf-8")
    (args.out / "rag_audit.md").write_text(report.to_markdown(), encoding="utf-8")
    print(report.to_markdown())
    print(
        f"LLM backend={settings.llm.backend} calls={len(client.usage.calls)} "
        f"cost=${client.usage.cost_usd:.4f}"
    )


if __name__ == "__main__":
    main()
