"""Course definition (concepts + prerequisite DAG) loaded from ``concepts.yaml``."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator

from mentora.db import Store
from mentora.db import models as m


class ConceptSpec(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    week: int | None = None
    prereqs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)

    @property
    def phrases(self) -> list[str]:
        """Strings that indicate this concept in text (used for passage tagging)."""
        return [self.name, self.key.replace("_", " "), *self.aliases]


class CourseSpec(BaseModel):
    code: str
    title: str
    concepts: list[ConceptSpec]
    starts_on: date | None = None

    def week_of(self, day: date) -> int | None:
        """Course week (1-based) for a date; None if the start date is unknown."""
        if self.starts_on is None:
            return None
        return max(1, (day - self.starts_on).days // 7 + 1)

    def concept(self, key: str) -> ConceptSpec | None:
        return next((c for c in self.concepts if c.key == key), None)

    @model_validator(mode="after")
    def _check_graph(self) -> Self:
        keys = [c.key for c in self.concepts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate concept keys")
        known = set(keys)
        for c in self.concepts:
            missing = set(c.prereqs) - known
            if missing:
                raise ValueError(f"{c.key}: unknown prerequisites {sorted(missing)}")
        # Kahn's algorithm: the prerequisite graph must be acyclic.
        indeg = {c.key: len(c.prereqs) for c in self.concepts}
        children: dict[str, list[str]] = {k: [] for k in keys}
        for c in self.concepts:
            for p in c.prereqs:
                children[p].append(c.key)
        queue = [k for k, d in indeg.items() if d == 0]
        seen = 0
        while queue:
            k = queue.pop()
            seen += 1
            for child in children[k]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    queue.append(child)
        if seen != len(keys):
            raise ValueError("prerequisite graph has a cycle")
        return self


def load_course(path: Path) -> CourseSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CourseSpec(
        code=raw["course"]["code"],
        title=raw["course"]["title"],
        starts_on=raw["course"].get("starts_on"),
        concepts=raw["concepts"],
    )


def upsert_course(db: Store, spec: CourseSpec) -> m.Course:
    """Create or update the course, its concepts and prerequisite edges."""
    course = db.find_one(m.Course, {"code": spec.code})
    if course is None:
        course = m.Course(code=spec.code, title=spec.title)
        db.add(course)
        db.flush()
    course.title = spec.title
    existing = {c.key: c for c in db.find(m.Concept, {"course_id": course.id})}
    for c in spec.concepts:
        row = existing.get(c.key)
        if row is None:
            row = m.Concept(course_id=course.id, key=c.key, name=c.name)
            db.add(row)
            existing[c.key] = row
        row.name = c.name
    db.flush()
    for c in spec.concepts:
        existing[c.key].prerequisite_ids = [existing[p].id for p in c.prereqs]
    db.flush()
    return course


class ItemSpec(BaseModel):
    external_id: str
    text: str
    answer_key: str
    item_type: Literal["mcq", "short"] = "short"
    concepts: list[str] = Field(min_length=1)
    graded: bool = False


def load_items(path: Path) -> list[ItemSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [ItemSpec.model_validate(i) for i in raw.get("items", [])]


def upsert_items(db: Store, course_id: int, items: list[ItemSpec]) -> dict[str, int]:
    """Create or update items and their concept tags; returns external_id -> item id."""
    concept_ids = {c.key: c.id for c in db.find(m.Concept, {"course_id": course_id})}
    existing = {
        i.external_id: i for i in db.find(m.Item, {"course_id": course_id}) if i.external_id
    }
    rows: dict[str, m.Item] = {}
    for spec in items:
        unknown = [k for k in spec.concepts if k not in concept_ids]
        if unknown:
            raise ValueError(f"item {spec.external_id}: unknown concepts {unknown}")
        row = existing.get(spec.external_id)
        if row is None:
            row = m.Item(course_id=course_id, external_id=spec.external_id, text=spec.text)
            db.add(row)
            existing[spec.external_id] = row
        row.text, row.answer_key = spec.text, spec.answer_key
        row.item_type, row.graded = spec.item_type, spec.graded
        row.concept_ids = sorted(concept_ids[k] for k in spec.concepts)
        rows[spec.external_id] = row
    db.flush()  # once: ids for new items, updates for changed ones
    return {ext: row.id for ext, row in rows.items()}


def item_concept_keys(db: Store, course_id: int) -> dict[int, list[str]]:
    """item id -> its concept keys, in concept id order."""
    keys = dict(db.values(m.Concept, ["id", "key"], {"course_id": course_id}))
    out: dict[int, list[str]] = {}
    for item_id, ids in db.values(m.Item, ["id", "concept_ids"], {"course_id": course_id}):
        tagged = [keys[c] for c in sorted(ids or []) if c in keys]
        if tagged:
            out[item_id] = tagged
    return out
