"""Replay a scripted session (YAML) through the orchestrator. Used by
scripts/replay_session.py and the end-to-end tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mentora.db import models as m
from mentora.orchestrator.turn import Orchestrator, TurnResult


def _item_id(db: Session, course_id: int, external_id: str) -> int:
    item_id = db.scalars(
        select(m.Item.id).where(m.Item.course_id == course_id, m.Item.external_id == external_id)
    ).first()
    if item_id is None:
        raise KeyError(f"unknown item {external_id}")
    return item_id


def replay(
    orch: Orchestrator,
    factory: sessionmaker[Session],
    script: list[dict[str, Any]] | Path,
    learner_id: str,
) -> tuple[str, list[tuple[str, TurnResult]]]:
    steps: list[dict[str, Any]] = (
        yaml.safe_load(script.read_text(encoding="utf-8"))["steps"]
        if isinstance(script, Path)
        else script
    )
    log: list[tuple[str, TurnResult]] = []
    session_id = ""
    with factory() as db:
        ids = {
            s[k]: _item_id(db, orch.course_id, s[k]) for s in steps for k in ("present",) if k in s
        }
        for s in steps:
            if "quiz" in s:
                for ext in s["quiz"]:
                    ids[ext] = _item_id(db, orch.course_id, ext)
            if "answer" in s:
                ext = s["answer"]["item"]
                ids[ext] = _item_id(db, orch.course_id, ext)
    for s in steps:
        if s.get("start"):
            r = orch.start_session(learner_id)
            session_id = r.session_id
            log.append(("start", r))
        elif "message" in s:
            log.append((f"message: {s['message']}", orch.handle_message(session_id, s["message"])))
        elif "quiz" in s:
            orch.start_quiz(session_id, [ids[x] for x in s["quiz"]])
        elif "present" in s:
            r = orch.present_item(session_id, ids[s["present"]])
            log.append((f"present: {s['present']}", r))
        elif "answer" in s:
            a = s["answer"]
            r = orch.handle_answer(
                session_id,
                ids[a["item"]],
                str(a["response"]),
                confidence=a.get("confidence"),
                response_seconds=a.get("seconds"),
            )
            log.append((f"answer: {a['response']} ({'right' if r.correct else 'wrong'})", r))
        elif s.get("end"):
            orch.end_session(session_id)
    return session_id, log
