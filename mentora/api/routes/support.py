"""Customer support: raise a complaint about anything in Mentora, and close the loop (D49).

Each complaint is saved as a ticket, emailed to the Mentora support inbox with the user's email
as reply-to (so support answers by replying), and confirmed to the user by email. The inbox email
carries a private "Mark as resolved" link: support writes what was fixed, the ticket is resolved
and the user is told by email. If it is not fixed, the user reopens it and support gets a new
email with a new link. Only the link token's hash is stored; a used link stops working.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from mentora.accounts import RateLimiter
from mentora.api.deps import User, current_user, db_session
from mentora.api.routes.accounts import _account
from mentora.config.settings import Settings
from mentora.db import Store
from mentora.db import models as m
from mentora.mail import Mailer, MailError

router = APIRouter(prefix="/api/support", tags=["support"])
log = logging.getLogger("mentora.support")

Db = Annotated[Store, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]

CATEGORIES = {
    "bug": "Something is not working",
    "account": "Account or sign-in",
    "content": "Wrong question or material",
    "ai_tutor": "AI tutor answer",
    "teacher": "Teacher or class",
    "other": "Something else",
}


def _inbox(s: Settings) -> str:
    return s.support_email or s.mail_from


def _limiter(request: Request, name: str = "support", per_hour: int = 5) -> RateLimiter:
    limits: dict[str, RateLimiter] = request.app.state.rate_limits
    if name not in limits:
        limits[name] = RateLimiter(per_hour, 3600)  # per account (or per IP for links)
    return limits[name]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _link_for(settings: Settings, ticket: m.SupportTicket) -> str:
    token = secrets.token_urlsafe(32)
    ticket.resolve_token = _hash(token)
    return f"{settings.public_base_url.rstrip('/')}/api/support/resolve/{ticket.id}?token={token}"


def _new_link(request: Request, ticket: m.SupportTicket) -> str:
    """A fresh private resolve link (the previous one stops working)."""
    return _link_for(request.app.state.settings, ticket)


def email_missing_resolve_links(db: Store, settings: Settings, mailer: Mailer) -> int:
    """Open requests raised before resolve links existed get one, emailed to the support inbox
    (once: a request that has a link is skipped). Run at start-up. Returns how many."""
    inbox = _inbox(settings)
    if not inbox:
        return 0
    sent = 0
    for ticket in db.find(m.SupportTicket, {"status": "open", "resolve_token": None}):
        account = db.get(m.Account, ticket.account_id)
        if account is None:
            continue
        link = _link_for(settings, ticket)
        if _send(
            mailer,
            inbox,
            f"[{ticket.number}] resolve link: {ticket.subject}",
            _inbox_text(
                ticket,
                account,
                link,
                f"Request {ticket.number} was sent before requests had a resolve link. Here it is.",
            ),
            reply_to=account.email,
        ):
            db.commit()
            sent += 1
        else:
            db.rollback()
    return sent


def _send(mailer: Mailer, to: str, subject: str, text: str, reply_to: str | None = None) -> bool:
    try:
        mailer.send(to, subject, text, reply_to=reply_to)
        return True
    except MailError:
        log.warning("support email %r to %s failed", subject, to, exc_info=True)
        return False


class TicketOut(BaseModel):
    number: str
    category: str
    category_label: str
    subject: str
    message: str
    page: str
    priority: str
    status: str
    created_at: datetime
    resolution: str
    resolved_at: datetime | None
    reopened: int


def _out(t: m.SupportTicket) -> TicketOut:
    return TicketOut(
        number=t.number,
        category=t.category,
        category_label=CATEGORIES.get(t.category, t.category),
        subject=t.subject,
        message=t.message,
        page=t.page,
        priority=t.priority,
        status=t.status,
        created_at=t.created_at,
        resolution=t.resolution,
        resolved_at=t.resolved_at,
        reopened=t.reopened,
    )


@router.get("")
def support_home(request: Request, user: Me, db: Db) -> dict[str, Any]:
    account = _account(db, user)
    rows = db.find(m.SupportTicket, {"account_id": account.id}, sort=[("created_at", -1)], limit=50)
    return {
        "email": _inbox(request.app.state.settings),
        "your_email": account.email,
        "categories": CATEGORIES,
        "tickets": [_out(t) for t in rows],
    }


class TicketIn(BaseModel):
    category: str
    subject: str = Field(max_length=200)
    message: str = Field(max_length=5000)
    page: str = Field(default="", max_length=200)
    priority: str = "normal"


def _who(account: m.Account) -> str:
    return f"{account.name} (@{account.username}, {account.role}) <{account.email}>"


def _inbox_text(t: m.SupportTicket, account: m.Account, link: str, heading: str) -> str:
    urgency = "High - it stops them from studying" if t.priority == "high" else "Normal"
    return (
        f"{heading}\n\n"
        f"From: {_who(account)}\n"
        f"Topic: {CATEGORIES.get(t.category, t.category)}\n"
        f"Priority: {urgency}\n"
        f"Where in Mentora: {t.page or 'not given'}\n"
        f"Sent: {t.created_at:%d %b %Y, %H:%M} UTC\n\n"
        f"Subject: {t.subject}\n\n{t.message}\n\n"
        "Reply to this email to answer the user directly.\n\n"
        f"When it is fixed, mark it as resolved (the user is told by email):\n{link}"
    )


@router.post("", status_code=201)
def raise_ticket(body: TicketIn, request: Request, user: Me, db: Db) -> TicketOut:
    account = _account(db, user)
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Choose what the problem is about.")
    if body.priority not in ("normal", "high"):
        raise HTTPException(422, "Choose a priority.")
    subject = " ".join(body.subject.split())
    message = body.message.strip()
    if len(subject) < 4:
        raise HTTPException(422, "Give your complaint a short title (at least 4 characters).")
    if len(message) < 10:
        raise HTTPException(422, "Describe the problem in a few words (at least 10 characters).")
    if not _limiter(request).allow(account.id):
        raise HTTPException(
            429, "You have sent several complaints this hour. Please wait a little."
        )
    ticket = m.SupportTicket(
        account_id=account.id,
        category=body.category,
        subject=subject,
        message=message,
        page=" ".join(body.page.split()),
        priority=body.priority,
    )
    db.add(ticket)
    db.flush()  # the number
    link = _new_link(request, ticket)
    db.commit()

    s: Settings = request.app.state.settings
    mailer: Mailer = request.app.state.mailer
    inbox = _inbox(s)
    if inbox:
        flag = " [HIGH]" if ticket.priority == "high" else ""
        ticket.emailed = _send(
            mailer,
            inbox,
            f"[{ticket.number}]{flag} {CATEGORIES[ticket.category]}: {subject}",
            _inbox_text(ticket, account, link, f"New support request {ticket.number}"),
            reply_to=account.email,
        )
    _send(
        mailer,
        account.email,
        f"We received your request {ticket.number}",
        f"Hi {account.name},\n\nThank you for contacting Mentora support. We have received "
        f"your request and given it the reference {ticket.number}.\n\n"
        f"Subject: {subject}\n\n{message}\n\n"
        "Our team usually replies within two working days, to this email address. To add "
        f"anything, write to {inbox or 'us'} and mention {ticket.number}.\n\nMentora support",
    )
    db.commit()
    return _out(ticket)


@router.post("/{number}/reopen")
def reopen(number: str, request: Request, user: Me, db: Db) -> TicketOut:
    """The user says it is not fixed: the request opens again and support gets a new link."""
    account = _account(db, user)
    try:
        ticket_id = int(number.upper().removeprefix("MEN-"))
    except ValueError as exc:
        raise HTTPException(404, "No such request.") from exc
    ticket = db.get(m.SupportTicket, ticket_id)
    if ticket is None or ticket.account_id != account.id:
        raise HTTPException(404, "No such request.")
    if ticket.status != "resolved":
        raise HTTPException(409, "This request is still open.")
    if not _limiter(request).allow(account.id):
        raise HTTPException(429, "Please wait a little before reopening again.")
    ticket.status, ticket.reopened = "open", ticket.reopened + 1
    link = _new_link(request, ticket)
    db.commit()
    inbox = _inbox(request.app.state.settings)
    if inbox:
        _send(
            request.app.state.mailer,
            inbox,
            f"[{ticket.number}] reopened: {ticket.subject}",
            _inbox_text(
                ticket,
                account,
                link,
                f"{account.name} says request {ticket.number} is not fixed yet and reopened it."
                f"\nYour earlier note: {ticket.resolution or '(none)'}",
            ),
            reply_to=account.email,
        )
    return _out(ticket)


# --- the private resolve page (opened from the support inbox; no sign-in) ---------------------

# The page shell (styles inline: it is opened from an email, outside the web app).
PAGE = Template((Path(__file__).parent.parent / "static" / "support_page.html").read_text("utf-8"))


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        PAGE.substitute(title=html.escape(title), body=body),
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _ticket_for(db: Store, ticket_id: int, token: str) -> m.SupportTicket | None:
    ticket = db.get(m.SupportTicket, ticket_id)
    if ticket is None or not ticket.resolve_token or not token:
        return None
    if not hmac.compare_digest(ticket.resolve_token, _hash(token)):
        return None
    return ticket


def _invalid() -> HTMLResponse:
    return _page(
        "Link not valid",
        "<h1>This link is not valid</h1><p class='muted'>It may have been used already, or the "
        "request was reopened and a newer email has the current link.</p>",
        404,
    )


@router.get("/resolve/{ticket_id}", include_in_schema=False)
def resolve_form(ticket_id: int, token: str, request: Request, db: Db) -> HTMLResponse:
    if not _limiter(request, "support-link", 60).allow(
        request.client.host if request.client else "x"
    ):
        return _page("Slow down", "<h1>Too many attempts</h1>", 429)
    ticket = _ticket_for(db, ticket_id, token)
    if ticket is None:
        return _invalid()
    account = db.get(m.Account, ticket.account_id)
    e = html.escape
    who = e(_who(account)) if account else "a deleted account"
    body = (
        f"<h1>Resolve {e(ticket.number)}</h1>"
        f"<p class='muted'>Write what was fixed. The user gets it by email and sees the "
        f"request as resolved.</p>"
        f"<div class='box'><dl><dt>From</dt><dd>{who}</dd>"
        f"<dt>Topic</dt><dd>{e(CATEGORIES.get(ticket.category, ticket.category))}</dd>"
        f"<dt>Priority</dt><dd>{'High' if ticket.priority == 'high' else 'Normal'}</dd>"
        f"<dt>Where</dt><dd>{e(ticket.page or 'not given')}</dd>"
        f"<dt>Sent</dt><dd>{ticket.created_at:%d %b %Y, %H:%M} UTC</dd></dl>"
        f"<div class='msg'><b>{e(ticket.subject)}</b>\n\n{e(ticket.message)}</div></div>"
        f"<form method='post' action='/api/support/resolve/{ticket.id}'>"
        f"<input type='hidden' name='token' value='{e(token)}'>"
        f"<label for='note'>What was fixed? (sent to the user)</label>"
        f"<textarea id='note' name='note' maxlength='3000' required "
        f"placeholder='e.g. We corrected question 4: the right answer is now TreeMap.'></textarea>"
        f"<button type='submit'>Mark as resolved and tell the user</button></form>"
    )
    return _page(f"Resolve {ticket.number}", body)


@router.post("/resolve/{ticket_id}", include_in_schema=False)
def resolve(
    ticket_id: int,
    request: Request,
    db: Db,
    token: Annotated[str, Form(max_length=200)],
    note: Annotated[str, Form(max_length=3000)],
) -> HTMLResponse:
    if not _limiter(request, "support-link", 60).allow(
        request.client.host if request.client else "x"
    ):
        return _page("Slow down", "<h1>Too many attempts</h1>", 429)
    ticket = _ticket_for(db, ticket_id, token)
    if ticket is None:
        return _invalid()
    text = note.strip()
    if len(text) < 3:
        return _page("Add a note", "<h1>Please write what was fixed</h1>", 422)
    ticket.status, ticket.resolution = "resolved", text
    ticket.resolved_at = datetime.now(UTC)
    ticket.resolve_token = None  # the link works once
    db.commit()
    account = db.get(m.Account, ticket.account_id)
    told = False
    if account is not None:
        told = _send(
            request.app.state.mailer,
            account.email,
            f"Your request {ticket.number} has been resolved",
            f"Hi {account.name},\n\nGood news: your request {ticket.number} "
            f'("{ticket.subject}") has been resolved.\n\nWhat we did:\n{text}\n\n'
            "If the problem is still there, open Help & support in Mentora and press Reopen "
            "next to this request, or reply to this email.\n\nMentora support",
            reply_to=_inbox(request.app.state.settings) or None,
        )
    e = html.escape
    done = (
        "The user has been emailed your note."
        if told
        else "Saved. The email to the user could not be sent; they will see it in Mentora."
    )
    return _page(
        f"{ticket.number} resolved",
        f"<h1>{e(ticket.number)} is resolved</h1>"
        f"<p class='ok'>{done}</p>"
        f"<div class='box'><b>Your note</b><div class='msg'>{e(text)}</div></div>",
    )
