"""Engagement features: session frequency, time on task, idle ratio and a logistic
dropout-risk score (weights in config, to be refitted on real data)."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from mentora.config.settings import LearnerModelSettings


@dataclass(frozen=True)
class Engagement:
    sessions_per_week: float
    time_on_task_hours: float
    idle_ratio: float
    dropout_risk: float


def _active_and_idle(times: Sequence[datetime], idle: timedelta) -> tuple[float, float]:
    active = idle_s = 0.0
    for a, b in itertools.pairwise(times):
        gap = (b - a).total_seconds()
        if gap <= idle.total_seconds():
            active += gap
        else:
            idle_s += gap
    return active, idle_s


def engagement(
    session_starts: Sequence[datetime],
    event_times: Sequence[datetime],
    current_session_events: Sequence[datetime],
    now: datetime,
    cfg: LearnerModelSettings,
) -> Engagement:
    window = timedelta(days=cfg.engagement_window_days)
    weeks = cfg.engagement_window_days / 7
    recent_sessions = [t for t in session_starts if now - window <= t <= now]
    idle = timedelta(minutes=cfg.idle_minutes)
    recent_events = sorted(t for t in event_times if now - window <= t <= now)
    active, _ = _active_and_idle(recent_events, idle)
    cur = sorted(current_session_events)
    cur_active, cur_idle = _active_and_idle(cur, idle)
    total = cur_active + cur_idle
    idle_ratio = cur_idle / total if total > 0 else 0.0

    spw = len(recent_sessions) / weeks
    hours = active / 3600
    w = cfg.dropout_weights
    z = (
        w.bias
        + w.sessions_per_week * spw
        + w.time_on_task_hours * hours
        + w.idle_ratio * idle_ratio
    )
    return Engagement(spw, hours, idle_ratio, 1 / (1 + math.exp(-z)))
