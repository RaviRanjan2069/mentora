"""The collections, references and indexes stay consistent with each other."""

from __future__ import annotations

from mentora.db import models as m
from mentora.db.client import INDEXES


def test_every_collection_has_indexes_and_known_references() -> None:
    names = {model.__collection__ for model in m.MODELS}
    assert set(INDEXES) <= names
    assert names - set(INDEXES) == {"learners"}  # looked up by _id only
    for model in m.MODELS:
        for field, ref in model.__refs__.items():
            assert ref.collection in names, f"{model.__name__}.{field} -> {ref.collection}"
            assert field in model.__dataclass_fields__, f"{model.__name__}.{field}"


def test_unique_constraints_from_sql_schema_v1_are_kept() -> None:
    unique = {
        name: [i.document["key"] for i in idx if i.document.get("unique")]
        for name, idx in INDEXES.items()
    }
    assert list(unique["courses"][0]) == ["code"]
    assert list(unique["concepts"][0]) == ["course_id", "key"]
    assert list(unique["transitions"][0]) == ["session_id", "t"]
