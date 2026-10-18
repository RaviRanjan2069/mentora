"""Memory items: create, quality update, learner view/delete, retention."""

from __future__ import annotations

from datetime import datetime, timedelta

from mentora.db import ASC, DESC, Store
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


def learner_items(db: Store, learner_id: str, course_id: int) -> list[m.MemoryItem]:
    """What a learner sees on the 'my memory' page (their own, active items)."""
    return db.find(
        m.MemoryItem,
        {
            "learner_id": learner_id,
            "course_id": course_id,
            "scope": "learner",
            "status": "active",
        },
        sort=[("created_at", DESC), ("id", DESC)],
    )


def delete_learner_item(db: Store, learner_id: str, item_id: int) -> bool:
    """A learner may delete only their own learner-scope items."""
    item = db.get(m.MemoryItem, item_id)
    if item is None or item.learner_id != learner_id or item.scope != "learner":
        return False
    db.delete(item)
    return True


def delete_all_learner_memory(db: Store, learner_id: str) -> int:
    return db.delete_many(m.MemoryItem, {"learner_id": learner_id})


def purge_expired(db: Store, retention_days: int, now: datetime) -> int:
    """Delete learner memory older than the retention limit (design rule 9)."""
    cutoff = now - timedelta(days=retention_days)
    return db.delete_many(m.MemoryItem, {"scope": "learner", "created_at": {"$lt": cutoff}})


def pending_course_items(db: Store, course_id: int) -> list[m.MemoryItem]:
    return db.find(
        m.MemoryItem,
        {"course_id": course_id, "scope": "course", "status": "pending_review"},
        sort=[("created_at", ASC), ("id", ASC)],
    )


def review_course_item(db: Store, item_id: int, approve: bool) -> m.MemoryItem:
    item = db.get(m.MemoryItem, item_id)
    if item is None or item.scope != "course" or item.status != "pending_review":
        raise ValueError(f"memory item {item_id} is not awaiting review")
    item.status = "active" if approve else "pruned"
    return item
