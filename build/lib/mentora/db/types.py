"""Column types that use native PostgreSQL features (jsonb, pgvector) and fall back to
plain JSON elsewhere, so unit tests run on SQLite without Docker (docs/decisions.md D3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Dialect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine

PortableJSON = JSON().with_variant(JSONB(), "postgresql")


class Embedding(TypeDecorator[list[float]]):
    """pgvector ``vector(dim)`` on PostgreSQL, a JSON float list elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if len(value) != self.dim:
            raise ValueError(f"embedding has {len(value)} dims, column expects {self.dim}")
        return [float(x) for x in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        return [float(x) for x in value]


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamps on every back-end (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use datetime.now(UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
