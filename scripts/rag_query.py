"""Show the top passages for a question.

python scripts/rag_query.py "what does range(5) produce?"
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from mentora.config import get_settings
from mentora.course import load_course
from mentora.db import make_engine, make_session_factory
from mentora.db import models as m
from mentora.rag import build_pipeline


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--max-week", type=int, default=None)
    args = ap.parse_args()

    factory = make_session_factory(make_engine())
    code = load_course(settings.app.concepts_file).code
    with factory() as db:
        course_id = db.scalars(select(m.Course.id).where(m.Course.code == code)).one()
    pipeline = build_pipeline(settings, factory, course_id)
    for rank, hit in enumerate(pipeline.search(args.question, max_week=args.max_week), 1):
        print(f"{rank}. [{hit.passage.id}] score={hit.score:.3f} ({hit.passage.section})")
        print(f"   {hit.passage.text[:200]}")


if __name__ == "__main__":
    main()
