"""The hand-written v1 migration must emit exactly the DDL the models produce.

Runs Alembic in offline (--sql) mode for PostgreSQL, so no database is needed.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from mentora.db import Base

ROOT = Path(__file__).resolve().parents[2]


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).replace("( ", "(").replace(" )", ")").strip().rstrip(";")


def _migration_statements() -> set[str]:
    buf = io.StringIO()
    cfg = Config(str(ROOT / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://u:p@localhost/x")
    command.upgrade(cfg, "head", sql=True)
    stmts = {_norm(s) for s in buf.getvalue().split(";")}
    wanted = {s for s in stmts if s.startswith(("CREATE TABLE", "CREATE INDEX"))}
    return {s for s in wanted if "alembic_version" not in s}


def _model_statements() -> set[str]:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    out: set[str] = set()
    for table in Base.metadata.sorted_tables:
        out.add(_norm(str(CreateTable(table).compile(dialect=dialect))))
        out |= {_norm(str(CreateIndex(ix).compile(dialect=dialect))) for ix in table.indexes}
    return out


def test_v1_migration_matches_models() -> None:
    migration, models = _migration_statements(), _model_statements()
    assert migration - models == set(), "in migration but not models"
    assert models - migration == set(), "in models but not migration"
