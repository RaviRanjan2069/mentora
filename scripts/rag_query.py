"""Show the top passages for a question.

python scripts/rag_query.py "what does range(5) produce?"
"""

from __future__ import annotations

import argparse

from mentora.config import get_settings
from mentora.course import load_course
from mentora.db import connect
from mentora.db import models as m
from mentora.rag import build_pipeline


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question")
    ap.add_argument("--max-week", type=int, default=None)
    args = ap.parse_args()

    factory = connect(settings.database_url)
    code = load_course(settings.app.concepts_file).code
    with factory() as db:
        row = db.find_one(m.Course, {"code": code})
        if row is None:
            raise SystemExit(f"course {code} not found; run scripts/seed_demo.py first")
        course_id = row.id
    pipeline = build_pipeline(settings, factory, course_id)
    for rank, hit in enumerate(pipeline.search(args.question, max_week=args.max_week), 1):
        print(f"{rank}. [{hit.passage.id}] score={hit.score:.3f} ({hit.passage.section})")
        print(f"   {hit.passage.text[:200]}")


if __name__ == "__main__":
    main()
