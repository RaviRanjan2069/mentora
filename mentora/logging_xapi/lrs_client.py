"""Learning Record Store interface. ``SqlLRSClient`` stores statements in the ``events``
collection (the name predates MongoDB); a real LRS (Ralph, Learning Locker) can be added
behind the same protocol."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from mentora.db import ASC, Store, StoreFactory
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
    def __init__(self, session_factory: StoreFactory) -> None:
        self._session_factory = session_factory

    def store(self, statement: Statement) -> str:
        return self.store_many([statement])[0]

    def store_many(self, statements: Sequence[Statement]) -> list[str]:
        with self._session_factory.begin() as db:
            for st in statements:
                self._add(db, st)
        return [st.id for st in statements]

    @staticmethod
    def _add(db: Store, st: Statement) -> None:
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
        filter: dict[str, Any] = {}
        if learner_id is not None:
            filter["learner_id"] = learner_id
        if session_id is not None:
            filter["session_id"] = session_id
        if verb is not None:
            filter["verb"] = VERBS.get(verb, verb)
        if since is not None:
            filter["timestamp"] = {"$gte": since}
        with self._session_factory() as db:
            rows = db.values(
                Event,
                ["statement"],
                filter,
                sort=[("timestamp", ASC), ("turn", ASC), ("seq", ASC)],
                limit=limit or 0,
            )
        return [Statement.model_validate(row) for (row,) in rows]
