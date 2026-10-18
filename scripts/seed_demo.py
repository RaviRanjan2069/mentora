"""Seed a demo database: course, concepts, quiz items, course material, the rule policy,
and (optionally) SIMULATED history so the teacher console has something to show.

    python scripts/seed_demo.py                         # course + items + material
                                                        # (+ the 1000-question bank)
    python scripts/seed_demo.py --with-history          # + simulated sessions, policy run

Simulated learners are named lrn_sim_* and are clearly synthetic. Do not run this against
a database that holds real learner data.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mentora.config import get_settings
from mentora.course import load_course, load_items, upsert_course, upsert_items
from mentora.db import Base, make_engine, make_session_factory
from mentora.policy import registry
from mentora.rag.embeddings import make_embedder
from mentora.rag.ingest import (
    PassageDraft,
    build_passages,
    embed_passages,
    load_documents,
    store_passages,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=ROOT / "data" / "sample" / "corpus")
    ap.add_argument("--items", type=Path, default=ROOT / "data" / "sample" / "items.yaml")
    ap.add_argument(
        "--bank",
        type=Path,
        default=ROOT / "data" / "sample" / "question_bank.yaml",
        help="generated MCQ bank (scripts/generate_question_bank.py); skipped if missing",
    )
    ap.add_argument(
        "--with-history",
        action="store_true",
        help="add simulated sessions and run the offline policy pipeline once",
    )
    ap.add_argument("--sessions", type=int, default=60)
    args = ap.parse_args()

    engine = make_engine(settings.database_url)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    else:
        print("PostgreSQL: make sure `alembic upgrade head` has been run.")
    factory = make_session_factory(engine)

    course = load_course(settings.app.concepts_file)
    with factory.begin() as db:
        course_id = upsert_course(db, course).id
        specs = load_items(args.items)
        if args.bank.exists():
            specs += load_items(args.bank)
        ids = upsert_items(db, course_id, specs)
        registry.ensure_rule_policy(db)
    print(f"Course {course.code}: {len(course.concepts)} concepts, {len(ids)} quiz items")

    if args.with_history:  # before ingest: the simulator indexes material with a test embedder
        from mentora.offline.simulator import LABEL, run_simulation
        from mentora.offline.train import run_offline_pipeline

        stats = run_simulation(settings, factory, n_sessions=args.sessions, turns=16, seed=42)
        print(
            f"History: {stats.sessions} {LABEL} sessions, {stats.turns} turns, "
            f"{stats.violations} constraint violations"
        )
        result = run_offline_pipeline(settings, factory, data_label="simulated demo history")
        print(f"Offline pipeline: {result.status} {result.version or ''}")
        for r in result.reasons:
            print(f"  - {r}")
    quarantined: list[PassageDraft] = []
    drafts = build_passages(
        load_documents(args.corpus),
        course,
        settings.rag.chunk_tokens,
        settings.rag.chunk_overlap_tokens,
        quarantined,
    )
    n = store_passages(factory, course_id, embed_passages(drafts, make_embedder(settings)))
    print(f"Course material: {n} passages ({settings.rag.embedder} embeddings)")
    for q in quarantined:
        print(f"  quarantined (instruction-like text): {q.source_file}")

    print("Done. Start the server: uvicorn mentora.api.main:app --reload")


if __name__ == "__main__":
    main()
