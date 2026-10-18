"""Recall: rank active items by cosine x quality x recency decay; return the top k.
Only the learner's own items and teacher-approved course items are candidates."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from mentora.db import ASC, Store
from mentora.db import models as m
from mentora.memory.service import RecalledItem


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0


def recall(
    db: Store,
    query_embedding: list[float],
    learner_id: str,
    course_id: int,
    *,
    k: int,
    half_life_days: float,
    now: datetime,
) -> list[RecalledItem]:
    rows = db.find(
        m.MemoryItem,
        {
            "course_id": course_id,
            "status": "active",
            "$or": [{"scope": "learner", "learner_id": learner_id}, {"scope": "course"}],
        },
        sort=[("id", ASC)],
    )
    q = np.asarray(query_embedding, dtype=float)
    scored = []
    for row in rows:
        if row.embedding is None:
            continue
        ref = row.last_used_at or row.created_at
        age_days = max((now - ref).total_seconds() / 86400, 0.0)
        decay = 0.5 ** (age_days / half_life_days)
        score = max(_cos(q, np.asarray(row.embedding)), 0.0) * row.quality * decay
        scored.append(RecalledItem(row.id, row.text, row.scope, score))
    scored.sort(key=lambda r: (r.score, r.id), reverse=True)
    return [r for r in scored[:k] if r.score > 0]
