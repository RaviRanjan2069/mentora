"""Ingest course material into corpus_passages.

python scripts/ingest_corpus.py --corpus data/sample/corpus --concepts data/concepts.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mentora.config import get_settings
from mentora.course import load_course, upsert_course
from mentora.db import connect
from mentora.rag.embeddings import make_embedder
from mentora.rag.ingest import (
    PassageDraft,
    build_passages,
    embed_passages,
    load_documents,
    store_passages,
)


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=Path("data/sample/corpus"))
    ap.add_argument("--concepts", type=Path, default=settings.app.concepts_file)
    ap.add_argument("--db-url", default=settings.database_url)
    args = ap.parse_args()

    factory = connect(args.db_url)

    course = load_course(args.concepts)
    with factory.begin() as db:
        course_id = upsert_course(db, course).id

    docs = load_documents(args.corpus)
    quarantined: list[PassageDraft] = []
    drafts = build_passages(
        docs, course, settings.rag.chunk_tokens, settings.rag.chunk_overlap_tokens, quarantined
    )

    passages = embed_passages(drafts, make_embedder(settings))
    n = store_passages(factory, course_id, passages)
    print(f"{course.code}: {len(docs)} documents -> {n} passages ({settings.rag.embedder})")
    for q in quarantined:
        print(
            f"  QUARANTINED (looks like instructions to the tutor): {q.source_file}: "
            f"{q.text[:120]!r}"
        )
    for p in passages:
        print(f"  {p.id:<40} week={p.week} tokens={p.token_count:<4} {list(p.concept_keys)}")


if __name__ == "__main__":
    main()
