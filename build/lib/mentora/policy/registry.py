"""Policy registry: every policy version with config, metrics, status and reasons.

Status flow: candidate -> approved/rejected (teacher) ; approved -> active (activation);
the previously active policy becomes retired. Only a teacher approval can activate a
learned policy. If nothing is active, the rule policy is."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mentora.db import models as m

RULE_VERSION = "rule-v1"


class RegistryError(Exception):
    pass


def ensure_rule_policy(db: Session) -> m.Policy:
    row = db.get(m.Policy, RULE_VERSION)
    if row is None:
        row = m.Policy(
            version=RULE_VERSION,
            type="rule",
            config={"rules": "mentora.policy.rule_policy.RULES"},
            metrics={},
            status="active",
            approved_by="initial configuration",
            reasons="Readable rule policy agreed with the teacher; the default policy.",
        )
        db.add(row)
        db.flush()
    return row


def active_policy(db: Session) -> m.Policy:
    row = db.scalars(select(m.Policy).where(m.Policy.status == "active")).first()
    return row if row is not None else ensure_rule_policy(db)


def register_candidate(
    db: Session,
    version: str,
    type_: str,
    config: dict[str, Any],
    metrics: dict[str, Any],
    reasons: str,
    status: str = "candidate",
) -> m.Policy:
    if db.get(m.Policy, version) is not None:
        raise RegistryError(f"policy {version} already registered")
    if status not in ("candidate", "rejected"):
        raise RegistryError("new policies start as candidate or rejected")
    row = m.Policy(
        version=version, type=type_, config=config, metrics=metrics, status=status, reasons=reasons
    )
    db.add(row)
    db.flush()
    return row


def decide(db: Session, version: str, *, approve: bool, teacher: str, note: str) -> m.Policy:
    """Teacher decision on a candidate. Approval activates it and retires the old policy."""
    row = db.get(m.Policy, version)
    if row is None:
        raise RegistryError(f"unknown policy {version}")
    if row.status != "candidate":
        raise RegistryError(f"policy {version} is {row.status}, not a candidate")
    now = datetime.now(UTC)
    row.decided_at = now
    row.approved_by = teacher
    row.reasons = f"{row.reasons or ''}\nTeacher decision: {note}".strip()
    if not approve:
        row.status = "rejected"
        return row
    for old in db.scalars(select(m.Policy).where(m.Policy.status == "active")):
        old.status = "retired"
    row.status = "active"
    db.flush()
    return row
