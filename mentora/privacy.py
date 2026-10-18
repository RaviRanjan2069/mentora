"""Pseudonymous learner identifiers (design rule 9)."""

from __future__ import annotations

import hashlib
import hmac


def pseudonymize(raw_id: str, salt: str) -> str:
    """Map an LMS user id to a stable pseudonym; the raw id is never stored."""
    digest = hmac.new(salt.encode(), raw_id.encode(), hashlib.sha256).hexdigest()
    return f"lrn_{digest[:32]}"
