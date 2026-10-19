"""Sending email (verification and password-reset links) through Brevo's transactional API.

Without ``MENTORA_BREVO_API_KEY`` nothing is sent: messages are logged instead (local development
and tests), and ``configured`` is false so new accounts count as verified.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from mentora.config.settings import Settings

log = logging.getLogger("mentora.mail")
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailError(Exception):
    """The email could not be sent."""


class Mailer(Protocol):
    configured: bool

    def send(self, to: str, subject: str, text: str, reply_to: str | None = None) -> None: ...


@dataclass
class LogMailer:
    """Development stand-in: records and logs messages instead of sending them."""

    configured: bool = False
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, text: str, reply_to: str | None = None) -> None:
        self.sent.append((to, subject, text))
        # A warning, so the link shows in development logs without any logging setup.
        log.warning("email not sent (no mail service configured) to %s: %s\n%s", to, subject, text)


class BrevoMailer:
    configured = True

    def __init__(
        self, api_key: str, sender: str, sender_name: str, timeout_s: float = 15.0
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"api-key": api_key, "accept": "application/json"},
        )
        self.sender, self.sender_name = sender, sender_name

    def send(self, to: str, subject: str, text: str, reply_to: str | None = None) -> None:
        body: dict[str, object] = {
            "sender": {"email": self.sender, "name": self.sender_name},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": _html(text),
            "textContent": text,
        }
        if reply_to:
            body["replyTo"] = {"email": reply_to}
        try:
            resp = self._client.post(BREVO_URL, json=body)
        except httpx.HTTPError as exc:
            raise MailError(f"mail service unreachable: {exc}") from exc
        if resp.status_code >= 400:
            # Never echo the API key; Brevo's error body names the problem (e.g. unverified sender).
            raise MailError(
                f"mail service refused the message: HTTP {resp.status_code} {resp.text[:200]}"
            )


def _html(text: str) -> str:
    """Plain text as simple HTML: escaped, paragraphs kept, bare links made clickable."""
    paras = []
    for block in text.split("\n\n"):
        escaped = html.escape(block)
        words = [
            f'<a href="{w}">{w}</a>' if w.startswith("https://") or w.startswith("http://") else w
            for w in escaped.split(" ")
        ]
        paras.append("<p>" + " ".join(words).replace("\n", "<br>") + "</p>")
    style = "font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#1f2937"
    return f'<html><body style="{style}">' + "".join(paras) + "</body></html>"


def make_mailer(settings: Settings) -> Mailer:
    key = settings.brevo_api_key.get_secret_value()
    if key and settings.mail_from:
        return BrevoMailer(key, settings.mail_from, settings.mail_from_name)
    return LogMailer()
