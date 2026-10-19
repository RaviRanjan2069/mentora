"""Accounts: passwords, user ids, one-time email links, rate limits, photos (D41).

Learning data stays keyed by the pseudonym ``Account.learner_id``; this module is the only
place that maps a person (email, name, photo) to that pseudonym.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

from mentora.db import Store
from mentora.db import models as m
from mentora.privacy import pseudonymize

USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._]{1,28})[a-z0-9]$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,253}\.[a-z]{2,24}$")
RESERVED = {"admin", "administrator", "root", "support", "mentora", "teacher", "student", "system"}

# scrypt: 16 MiB of memory per hash, fine on a 512 MB instance; parameters stored with the hash.
_N, _R, _P = 2**14, 8, 1


class AccountError(ValueError):
    """A request about an account that cannot be done; the message is safe to show."""


# --- passwords -----------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    enc = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${enc(salt).decode()}${enc(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def check_password_rules(password: str, username: str, email: str, minimum: int) -> None:
    if len(password) < minimum:
        raise AccountError(f"Use a password of at least {minimum} characters.")
    if len(password) > 128:
        raise AccountError("Use a password of at most 128 characters.")
    lowered = password.lower()
    if lowered in (username, email) or lowered == email.split("@")[0]:
        raise AccountError("Your password cannot be your user id or email.")
    if len(set(password)) < 4:
        raise AccountError("That password is too easy to guess.")


# --- user ids and emails ---------------------------------------------------------------------


def normalize_username(raw: str) -> str:
    name = raw.strip().lower()
    if not USERNAME_RE.match(name) or ".." in name or "__" in name:
        raise AccountError(
            "Your user id needs 3-30 characters: letters, digits, dots or underscores, "
            "starting and ending with a letter or digit."
        )
    if name in RESERVED:
        raise AccountError("That user id is reserved. Please choose another.")
    return name


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AccountError("Please enter a valid email address.")
    return email


CLASS_CODE_RE = re.compile(r"^[A-Z0-9](?:[A-Z0-9-]{2,18})[A-Z0-9]$")


def normalize_class_code(raw: str) -> str:
    code = "".join(raw.split()).upper()  # "12345 67890" works too
    if not CLASS_CODE_RE.match(code) or "--" in code:
        raise AccountError(
            "Use 4-20 letters, digits or hyphens for the class code, e.g. RAO-PYTHON."
        )
    return code


CLASS_CODE_DIGITS = 10


def random_class_code() -> str:
    """10 random digits, not starting with 0."""
    low = 10 ** (CLASS_CODE_DIGITS - 1)
    return str(low + secrets.randbelow(9 * low))


def is_new_class_code(code: str) -> bool:
    return len(code) == CLASS_CODE_DIGITS and code.isdigit() and code[0] != "0"


def free_class_code(db: Store) -> str:
    """A random class code no teacher has yet."""
    while True:
        code = random_class_code()
        if db.get(m.ClassCode, code) is None:
            return code


def give_class_code(db: Store, account: m.Account, code: str | None = None) -> m.ClassCode:
    """The teacher's permanent class code (``code`` if given, else a random free one)."""
    row = m.ClassCode(
        id=code or free_class_code(db),
        teacher_id=account.id,
        teacher_username=account.username,
        teacher_name=account.name,
    )
    db.add(row)
    return row


def username_taken(db: Store, username: str) -> bool:
    return db.count(m.Account, {"username": username}) > 0


def find_by_login(db: Store, login: str) -> m.Account | None:
    """A user id or an email address."""
    key = login.strip().lower()
    return db.find_one(m.Account, {"email": key} if "@" in key else {"username": key})


def learner_pseudonym(account_id: str, salt: str) -> str:
    return pseudonymize(f"acct|{account_id}", salt)


# --- one-time email links --------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Store, account: m.Account, purpose: str, hours: float) -> str:
    """A new one-time token; earlier unused ones for the same purpose stop working."""
    db.update_many(
        m.EmailToken, {"account_id": account.id, "purpose": purpose, "used": False}, {"used": True}
    )
    token = secrets.token_urlsafe(32)
    db.add(
        m.EmailToken(
            id=_token_hash(token),
            purpose=purpose,
            account_id=account.id,
            expires_at=datetime.now(UTC) + timedelta(hours=hours),
        )
    )
    db.flush()
    return token


def use_token(db: Store, token: str, purpose: str) -> m.Account:
    row = db.get(m.EmailToken, _token_hash(token.strip()))
    if row is None or row.purpose != purpose or row.used or row.expires_at < datetime.now(UTC):
        raise AccountError("This link is invalid or has expired. Please request a new one.")
    account = db.get(m.Account, row.account_id)
    if account is None:
        raise AccountError("This link is invalid or has expired. Please request a new one.")
    row.used = True
    return account


# --- rate limits -----------------------------------------------------------------------------


class RateLimiter:
    """At most ``limit`` events per ``window_s`` per key (in memory, one process)."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window_s = limit, window_s
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._events) > 50_000:  # bound memory under abuse
                self._events = {k: v for k, v in self._events.items() if v}
            return True


# --- photos ----------------------------------------------------------------------------------

_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def photo_type(data: bytes) -> str:
    """The image type from the file's first bytes (never from the name or the browser)."""
    for magic, kind in _SIGNATURES:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise AccountError("Please upload a JPEG, PNG or WebP image.")


# --- deleting -------------------------------------------------------------------------------


def delete_account(db: Store, account: m.Account) -> None:
    """The account, its photo, links and tokens, and all learning data under its pseudonym."""
    if account.learner_id:
        db.delete_many(m.Learner, {"id": account.learner_id})
    db.delete_many(m.Account, {"id": account.id})
