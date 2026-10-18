"""Memory items: create, quality update, learner view/delete, retention."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mentora.db import models as m


def quality(n_plus: int, n_minus: int) -> float:
    """q = (n_plus + 1) / (n_plus + n_minus + 2)."""
    return (n_plus + 1) / (n_plus + n_minus + 2)


def record_outcome(item: m.MemoryItem, helped: bool, now: datetime) -> None:
    if helped:
        item.n_plus += 1
    else:
        item.n_minus += 1
    item.quality = quality(item.n_plus, item.n_minus)
    item.last_used_at = now


def learner_items(db: Session, learner_id: str, course_id: int) -> list[m.MemoryItem]:
    """What a learner sees on the 'my memory' page (their own, active items)."""
    return list(
        db.scalars(
            select(m.MemoryItem)
            .where(
                m.MemoryItem.learner_id == learner_id,
                m.MemoryItem.course_id == course_id,
                m.MemoryItem.scope == "learner",
                m.MemoryItem.status == "active",
            )
            .order_by(m.MemoryItem.created_at.desc())
        )
    )


def delete_learner_item(db: Session, learner_id: str, item_id: int) -> bool:
    """A learner may delete only their own learner-scope items."""
    item = db.get(m.MemoryItem, item_id)
    if item is None or item.learner_id != learner_id or item.scope != "learner":
        return False
    db.delete(item)
    return True


def delete_all_learner_memory(db: Session, learner_id: str) -> int:
    result = db.execute(delete(m.MemoryItem).where(m.MemoryItem.learner_id == learner_id))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def purge_expired(db: Session, retention_days: int, now: datetime) -> int:
    """Delete learner memory older than the retention limit (design rule 9)."""
    cutoff = now - timedelta(days=retention_days)
    result = db.execute(
        delete(m.MemoryItem).where(
            m.MemoryItem.scope == "learner", m.MemoryItem.created_at < cutoff
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def pending_course_items(db: Session, course_id: int) -> list[m.MemoryItem]:
    return list(
        db.scalars(
            select(m.MemoryItem)
            .where(
                m.MemoryItem.course_id == course_id,
                m.MemoryItem.scope == "course",
                m.MemoryItem.status == "pending_review",
            )
            .order_by(m.MemoryItem.created_at)
        )
    )


def review_course_item(db: Session, item_id: int, approve: bool) -> m.MemoryItem:
    item = db.get(m.MemoryItem, item_id)
    if item is None or item.scope != "course" or item.status != "pending_review":
        raise ValueError(f"memory item {item_id} is not awaiting review")
    item.status = "active" if approve else "pruned"
    return item
