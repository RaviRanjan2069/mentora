"""Unit of work over MongoDB, with the semantics the code relied on from SQLAlchemy:

- an identity map (one object per document per Store);
- ``add`` then ``flush`` / ``commit`` writes; integer ids come from a ``counters``
  collection, so ``obj.id`` is set after ``flush()``;
- changed attributes of loaded objects are written on ``flush`` / ``commit`` (dirty
  tracking by snapshot), so "load, mutate, commit" keeps working;
- references are checked on insert and cascade / set-null on delete;
- ``rollback`` (and leaving ``begin()`` with an exception, or a Store without commit)
  undoes everything flushed since the last commit, from an undo journal. A standalone
  MongoDB has no multi-document transactions, so a crash in the middle of a flush can
  leave a partial write (docs/decisions.md D40).
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from mentora.db.documents import Document, IntegrityError
from mentora.db.models import MODELS

D = TypeVar("D", bound=Document)
Filter = Mapping[str, Any]
Sort = Sequence[tuple[str, int]]
ASC, DESC = 1, -1

# Undo journal entry: (collection, _id, document before the write or None if it was new).
_Undo = tuple[str, Any, dict[str, Any] | None]


def _translate(model: type[Document], spec: Any) -> Any:
    """Use the model's primary-key field name in filters and sorts; Mongo calls it _id."""
    pk = model.__pk__
    if isinstance(spec, Mapping):
        out: dict[str, Any] = {}
        for key, value in spec.items():
            if key in ("$or", "$and", "$nor"):
                out[key] = [_translate(model, v) for v in value]
            else:
                out["_id" if key == pk else key] = value
        return out
    if isinstance(spec, list | tuple):
        return [("_id" if k == pk else k, d) for k, d in spec]
    return spec


class Store:
    def __init__(self, database: Database[dict[str, Any]]) -> None:
        self.db = database
        self._identity: dict[tuple[str, Any], Document] = {}
        self._snapshots: dict[tuple[str, Any], dict[str, Any]] = {}
        self._pending: list[Document] = []
        self._journal: list[_Undo] = []
        self._known: set[tuple[str, Any]] = set()  # references already checked

    # --- context management ----------------------------------------------------------

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Like closing an SQL session without commit: uncommitted writes are undone."""
        self.rollback()

    # --- unit of work ------------------------------------------------------------------

    def collection(self, model: type[Document]) -> Collection[dict[str, Any]]:
        return self.db[model.__collection__]

    def add(self, obj: Document) -> None:
        if obj not in self._pending and self._key(obj) not in self._identity:
            self._pending.append(obj)

    def add_all(self, objs: Iterable[Document]) -> None:
        for obj in objs:
            self.add(obj)

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for obj in pending:
            self._insert(obj)
        for key, obj in list(self._identity.items()):
            self._update_if_dirty(key, obj)

    def commit(self) -> None:
        self.flush()
        self._journal.clear()

    def rollback(self) -> None:
        self._pending.clear()
        for name, _id, before in reversed(self._journal):
            coll = self.db[name]
            if before is None:
                coll.delete_one({"_id": _id})
            else:
                coll.replace_one({"_id": _id}, before, upsert=True)
        self._journal.clear()
        self._identity.clear()
        self._snapshots.clear()
        self._known.clear()

    @contextmanager
    def begin_nested(self) -> Iterator[Store]:
        """Savepoint: writes inside are undone if the block raises; the outer unit of
        work goes on."""
        self.flush()
        mark = len(self._journal)
        try:
            yield self
            self.flush()
        except BaseException:
            self._pending.clear()
            undo, self._journal = self._journal[mark:], self._journal[:mark]
            for name, _id, before in reversed(undo):
                if before is None:
                    self.db[name].delete_one({"_id": _id})
                    self._forget(name, _id)
                else:
                    self.db[name].replace_one({"_id": _id}, before, upsert=True)
                    self._forget(name, _id)
            raise

    # --- reads -----------------------------------------------------------------------

    def get(self, model: type[D], pk: Any) -> D | None:
        key = (model.__collection__, pk)
        if key in self._identity:
            return self._identity[key]  # type: ignore[return-value]
        for obj in self._pending:
            if isinstance(obj, model) and obj.pk == pk:
                return obj
        raw = self.collection(model).find_one({"_id": pk})
        return None if raw is None else self._track(model, raw)

    def find(
        self,
        model: type[D],
        filter: Filter | None = None,
        *,
        sort: Sort | None = None,
        limit: int = 0,
    ) -> list[D]:
        self.flush()
        cursor = self.collection(model).find(_translate(model, dict(filter or {})))
        if sort:
            cursor = cursor.sort(_translate(model, list(sort)))
        if limit:
            cursor = cursor.limit(limit)
        return [self._track(model, raw) for raw in cursor]

    def find_one(
        self, model: type[D], filter: Filter | None = None, *, sort: Sort | None = None
    ) -> D | None:
        rows = self.find(model, filter, sort=sort, limit=1)
        return rows[0] if rows else None

    def count(self, model: type[Document], filter: Filter | None = None) -> int:
        self.flush()
        return self.collection(model).count_documents(_translate(model, dict(filter or {})))

    def distinct(
        self, model: type[Document], field: str, filter: Filter | None = None
    ) -> list[Any]:
        self.flush()
        name = "_id" if field == model.__pk__ else field
        return list(self.collection(model).distinct(name, _translate(model, dict(filter or {}))))

    def values(
        self,
        model: type[Document],
        fields: Sequence[str],
        filter: Filter | None = None,
        *,
        sort: Sort | None = None,
        limit: int = 0,
    ) -> list[tuple[Any, ...]]:
        """Selected fields only, as tuples (SQL ``select(m.X.a, m.X.b)``); not tracked."""
        self.flush()
        names = ["_id" if f == model.__pk__ else f for f in fields]
        cursor = self.collection(model).find(
            _translate(model, dict(filter or {})), {n: 1 for n in names}
        )
        if sort:
            cursor = cursor.sort(_translate(model, list(sort)))
        if limit:
            cursor = cursor.limit(limit)
        return [tuple(raw.get(n) for n in names) for raw in cursor]

    # --- bulk writes -----------------------------------------------------------------

    def delete(self, obj: Document) -> None:
        if obj in self._pending:
            self._pending.remove(obj)
            return
        self.delete_many(type(obj), {type(obj).__pk__: obj.pk})

    def delete_many(self, model: type[Document], filter: Filter) -> int:
        """Delete matching documents and apply reference cascades. Returns the count."""
        self.flush()
        return self._delete_where(model.__collection__, _translate(model, dict(filter)))

    def update_many(self, model: type[Document], filter: Filter, values: Mapping[str, Any]) -> int:
        self.flush()
        coll = self.collection(model)
        n = 0
        for raw in list(coll.find(_translate(model, dict(filter)))):
            obj = model.from_mongo(raw)
            for name, value in values.items():
                setattr(obj, name, value)
            for name, factory in model.__onupdate__.items():
                setattr(obj, name, factory())
            obj.validate()
            new = obj.to_mongo()
            self._journal.append((model.__collection__, raw["_id"], raw))
            coll.replace_one({"_id": raw["_id"]}, new)
            key = (model.__collection__, raw["_id"])
            if key in self._identity:
                tracked = self._identity[key]
                for name, value in values.items():
                    setattr(tracked, name, getattr(obj, name))
                self._snapshots[key] = copy.deepcopy(tracked.to_mongo())
            n += 1
        return n

    # --- internals -------------------------------------------------------------------

    def _key(self, obj: Document) -> tuple[str, Any]:
        return (obj.__collection__, obj.pk)

    def _track(self, model: type[D], raw: Mapping[str, Any]) -> D:
        key = (model.__collection__, raw["_id"])
        if key in self._identity:
            return self._identity[key]  # type: ignore[return-value]
        obj = model.from_mongo(raw)
        self._identity[key] = obj
        self._snapshots[key] = copy.deepcopy(obj.to_mongo())
        self._known.add(key)
        return obj

    def _forget(self, name: str, _id: Any) -> None:
        self._identity.pop((name, _id), None)
        self._snapshots.pop((name, _id), None)
        self._known.discard((name, _id))

    def _next_id(self, name: str) -> int:
        doc = self.db["counters"].find_one_and_update(
            {"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        return int(doc["seq"])

    def _check_refs(self, obj: Document, fields: Iterable[str] | None = None) -> None:
        for name, ref in obj.__refs__.items():
            if fields is not None and name not in fields:
                continue
            value = getattr(obj, name)
            if value is None or (ref.collection, value) in self._known:
                continue
            if self.db[ref.collection].count_documents({"_id": value}, limit=1) == 0:
                raise IntegrityError(f"{obj.__collection__}.{name}={value!r}: no such row")
            self._known.add((ref.collection, value))

    def _insert(self, obj: Document) -> None:
        kind = obj.__id_kind__
        if kind == "counter" and not obj.pk:
            setattr(obj, obj.__pk__, self._next_id(obj.__collection__))
        elif kind == "uuid" and not obj.pk:
            setattr(obj, obj.__pk__, str(uuid4()))
        obj.validate()
        self._check_refs(obj)
        raw = obj.to_mongo()
        try:
            self.db[obj.__collection__].insert_one(raw)
        except DuplicateKeyError as exc:
            raise IntegrityError(str(exc)) from exc
        key = self._key(obj)
        self._journal.append((obj.__collection__, obj.pk, None))
        self._identity[key] = obj
        self._snapshots[key] = copy.deepcopy(raw)
        self._known.add(key)

    def _update_if_dirty(self, key: tuple[str, Any], obj: Document) -> None:
        before = self._snapshots[key]
        current = obj.to_mongo()
        changed = {k: v for k, v in current.items() if before.get(k) != v}
        if not changed:
            return
        for name, factory in obj.__onupdate__.items():
            setattr(obj, name, factory())
        obj.validate()
        self._check_refs(obj, changed)
        current = obj.to_mongo()
        try:
            self.db[obj.__collection__].replace_one({"_id": current["_id"]}, current)
        except DuplicateKeyError as exc:
            raise IntegrityError(str(exc)) from exc
        self._journal.append((obj.__collection__, current["_id"], before))
        self._snapshots[key] = copy.deepcopy(current)

    def _delete_where(self, name: str, filter: Mapping[str, Any]) -> int:
        """Set-based delete with cascades: one find and one delete per collection and
        level, not per document (Atlas M0 allows 100 operations per second)."""
        coll = self.db[name]
        docs = list(coll.find(dict(filter)))
        if not docs:
            return 0
        ids = [d["_id"] for d in docs]
        # Children first, so a failure leaves no orphans behind.
        for model in MODELS:
            for field_name, ref in model.__refs__.items():
                if ref.collection != name:
                    continue
                child = {field_name: {"$in": ids}}
                if ref.on_delete == "cascade":
                    self._delete_where(model.__collection__, child)
                else:
                    self._set_null(model.__collection__, field_name, child)
        coll.delete_many({"_id": {"$in": ids}})
        for d in docs:
            self._journal.append((name, d["_id"], d))
            self._forget(name, d["_id"])
        return len(docs)

    def _set_null(self, name: str, field_name: str, filter: Mapping[str, Any]) -> None:
        coll = self.db[name]
        docs = list(coll.find(dict(filter)))
        if not docs:
            return
        coll.update_many({"_id": {"$in": [d["_id"] for d in docs]}}, {"$set": {field_name: None}})
        for d in docs:
            self._journal.append((name, d["_id"], d))
            key = (name, d["_id"])
            if key in self._identity:
                setattr(self._identity[key], field_name, None)
                self._snapshots[key][field_name] = None


class StoreFactory:
    """Replaces ``sessionmaker``: ``factory()`` opens a Store; ``factory.begin()`` commits
    on success and rolls back on an exception."""

    def __init__(self, database: Database[dict[str, Any]]) -> None:
        self.database = database

    def __call__(self) -> Store:
        return Store(self.database)

    @contextmanager
    def begin(self) -> Iterator[Store]:
        store = Store(self.database)
        try:
            yield store
            store.commit()
        except BaseException:
            store.rollback()
            raise
