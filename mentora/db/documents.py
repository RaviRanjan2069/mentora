"""Document base for MongoDB collections (docs/decisions.md D40).

Models are keyword-only dataclasses. The primary key field is stored as ``_id``. Things a
relational database used to enforce are declared here and enforced by ``Store``:
references (foreign keys with cascade / set-null), ``validate()`` (CHECK constraints) and
unique indexes (``mentora.db.client.ensure_schema``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Self

IdKind = Literal["counter", "uuid", "given"]
OnDelete = Literal["cascade", "set_null"]


class IntegrityError(Exception):
    """A write broke a reference, unique index or constraint (the SQL IntegrityError)."""


@dataclass(frozen=True)
class Ref:
    collection: str
    on_delete: OnDelete


def now() -> datetime:
    return truncate(datetime.now(UTC))


def truncate(value: datetime) -> datetime:
    """MongoDB stores milliseconds; keep in-memory values identical to stored ones."""
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


@dataclass(kw_only=True)
class Document:
    __collection__: ClassVar[str]
    __pk__: ClassVar[str] = "id"
    __id_kind__: ClassVar[IdKind] = "counter"
    __refs__: ClassVar[Mapping[str, Ref]] = {}
    # field -> factory applied whenever an existing document is updated (SQL onupdate)
    __onupdate__: ClassVar[Mapping[str, Callable[[], Any]]] = {}

    def validate(self) -> None:
        """Raise IntegrityError when the document breaks a constraint."""

    @property
    def pk(self) -> Any:
        return getattr(self, self.__pk__)

    def to_mongo(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    raise ValueError("naive datetime; use datetime.now(UTC)")
                value = truncate(value.astimezone(UTC))
                setattr(self, f.name, value)
            raw["_id" if f.name == self.__pk__ else f.name] = value
        return raw

    @classmethod
    def from_mongo(cls, raw: Mapping[str, Any]) -> Self:
        names = {f.name for f in dataclasses.fields(cls)}
        values: dict[str, Any] = {}
        for key, value in raw.items():
            name = cls.__pk__ if key == "_id" else key
            if name not in names:
                continue  # fields removed from the model are ignored, not fatal
            if isinstance(value, datetime):
                value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
            values[name] = value
        return cls(**values)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def one_of(value: str, allowed: tuple[str, ...], field: str) -> None:
    check(value in allowed, f"{field}={value!r} not in {allowed}")


def embedding_ok(value: list[float] | None, dim: int, field: str) -> list[float] | None:
    if value is None:
        return None
    if len(value) != dim:
        raise ValueError(f"{field} has {len(value)} dims, expected {dim}")
    return [float(x) for x in value]
