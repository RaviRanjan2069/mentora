"""Course definition (concepts + prerequisite DAG) loaded from ``concepts.yaml``."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def upsert_course(db: Session, spec: CourseSpec) -> m.Course:
    """Create or update the course, its concepts and prerequisite edges."""
    course = db.scalars(select(m.Course).where(m.Course.code == spec.code)).one_or_none()
    if course is None:
        course = m.Course(code=spec.code, title=spec.title)
        db.add(course)
        db.flush()
    course.title = spec.title
    existing = {
        c.key: c for c in db.scalars(select(m.Concept).where(m.Concept.course_id == course.id))
    }
    for c in spec.concepts:
        row = existing.get(c.key)
        if row is None:
            row = m.Concept(course_id=course.id, key=c.key, name=c.name)
            db.add(row)
            existing[c.key] = row
        row.name = c.name
    db.flush()
    ids = [existing[c.key].id for c in spec.concepts]
    db.execute(
        m.concept_prerequisites.delete().where(m.concept_prerequisites.c.concept_id.in_(ids))
    )
    edges = [
        {"concept_id": existing[c.key].id, "prerequisite_id": existing[p].id}
        for c in spec.concepts
        for p in c.prereqs
    ]
    if edges:
        db.execute(m.concept_prerequisites.insert(), edges)
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


def upsert_items(db: Session, course_id: int, items: list[ItemSpec]) -> dict[str, int]:
    """Create or update items and their concept tags; returns external_id -> item id."""
    concept_ids = {
        c.key: c.id for c in db.scalars(select(m.Concept).where(m.Concept.course_id == course_id))
    }
    existing = {
        i.external_id: i
        for i in db.scalars(select(m.Item).where(m.Item.course_id == course_id))
        if i.external_id
    }
    out: dict[str, int] = {}
    for spec in items:
        unknown = [k for k in spec.concepts if k not in concept_ids]
        if unknown:
            raise ValueError(f"item {spec.external_id}: unknown concepts {unknown}")
        row = existing.get(spec.external_id)
        if row is None:
            row = m.Item(course_id=course_id, external_id=spec.external_id, text=spec.text)
            db.add(row)
        row.text, row.answer_key = spec.text, spec.answer_key
        row.item_type, row.graded = spec.item_type, spec.graded
        db.flush()
        db.execute(m.item_concepts.delete().where(m.item_concepts.c.item_id == row.id))
        db.execute(
            m.item_concepts.insert(),
            [{"item_id": row.id, "concept_id": concept_ids[k]} for k in spec.concepts],
        )
        out[spec.external_id] = row.id
    return out


def item_concept_keys(db: Session, course_id: int) -> dict[int, list[str]]:
    rows = db.execute(
        select(m.item_concepts.c.item_id, m.Concept.key)
        .join(m.Concept, m.Concept.id == m.item_concepts.c.concept_id)
        .where(m.Concept.course_id == course_id)
        .order_by(m.item_concepts.c.item_id, m.Concept.id)
    ).all()
    out: dict[int, list[str]] = {}
    for item_id, key in rows:
        out.setdefault(item_id, []).append(key)
    return out
