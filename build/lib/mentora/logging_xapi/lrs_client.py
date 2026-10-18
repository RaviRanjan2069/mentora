"""Learning Record Store interface. ``SqlLRSClient`` stores statements in the ``events``
table; a real LRS (Ralph, Learning Locker) can be added behind the same protocol."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mentora.db.models import Event
from mentora.logging_xapi.statements import VERBS, Statement


class StatementConflictError(Exception):
    """A statement id was reused with different content (xAPI: 409 Conflict)."""


class LRSClient(Protocol):
    def store(self, statement: Statement) -> str: ...

    def store_many(self, statements: Sequence[Statement]) -> list[str]: ...

    def query(
        self,
        *,
        learner_id: str | None = None,
        session_id: str | None = None,
        verb: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Statement]: ...


class SqlLRSClient:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def store(self, statement: Statement) -> str:
        return self.store_many([statement])[0]

    def store_many(self, statements: Sequence[Statement]) -> list[str]:
        with self._session_factory.begin() as db:
            for st in statements:
                self._add(db, st)
        return [st.id for st in statements]

    @staticmethod
    def _add(db: Session, st: Statement) -> None:
        payload = st.to_json_dict()
        existing = db.get(Event, st.id)
        if existing is not None:
            if existing.statement != payload:
                raise StatementConflictError(st.id)
            return
        ext = st.tutor_action
        db.add(
            Event(
                id=st.id,
                learner_id=st.learner_id,
                session_id=st.session_id,
                turn=st.turn,
                verb=st.verb.id,
                object_id=st.object_.id,
                timestamp=st.timestamp,
                statement=payload,
                policy_version=ext.policy_version if ext else None,
                action_id=ext.action.id if ext else None,
                propensity=ext.propensity if ext else None,
                escalated=ext.escalated if ext else None,
            )
        )

    def query(
        self,
        *,
        learner_id: str | None = None,
        session_id: str | None = None,
        verb: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Statement]:
        stmt = select(Event.statement)
        if learner_id is not None:
            stmt = stmt.where(Event.learner_id == learner_id)
        if session_id is not None:
            stmt = stmt.where(Event.session_id == session_id)
        if verb is not None:
            stmt = stmt.where(Event.verb == VERBS.get(verb, verb))
        if since is not None:
            stmt = stmt.where(Event.timestamp >= since)
        stmt = stmt.order_by(Event.timestamp, Event.turn, Event.stored_at)
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._session_factory() as db:
            return [Statement.model_validate(row) for row in db.scalars(stmt)]
