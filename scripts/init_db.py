"""Create Mentora's MongoDB indexes and record the schema version (idempotent).

    python scripts/init_db.py                     # MENTORA_DATABASE_URL or the default
    python scripts/init_db.py --db mongodb://localhost:27017/mentora

The API does the same on start; this is for setting up a database before first use.
"""

from __future__ import annotations

import argparse

from mentora.config import get_settings
from mentora.db import SCHEMA_VERSION, connect
from mentora.db.client import INDEXES


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=get_settings().database_url)
    args = ap.parse_args()
    factory = connect(args.db)
    print(
        f"Schema {SCHEMA_VERSION}: {sum(len(i) for i in INDEXES.values())} indexes on "
        f"{len(INDEXES)} collections in database {factory.database.name!r}"
    )


if __name__ == "__main__":
    main()
