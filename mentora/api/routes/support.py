"""Customer support: raise a complaint about anything in Mentora (D49).

Each complaint is saved as a ticket, emailed to the Mentora support inbox with the user's email
as reply-to (so support answers by replying), and confirmed to the user by email.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
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


def _limiter(request: Request) -> RateLimiter:
    limits: dict[str, RateLimiter] = request.app.state.rate_limits
    if "support" not in limits:
        limits["support"] = RateLimiter(5, 3600)  # complaints per hour per account
    return limits["support"]


class TicketOut(BaseModel):
    number: str
    category: str
    category_label: str
    subject: str
    message: str
    page: str
    status: str
    created_at: datetime


def _out(t: m.SupportTicket) -> TicketOut:
    return TicketOut(
        number=t.number,
        category=t.category,
        category_label=CATEGORIES.get(t.category, t.category),
        subject=t.subject,
        message=t.message,
        page=t.page,
        status=t.status,
        created_at=t.created_at,
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


@router.post("", status_code=201)
def raise_ticket(body: TicketIn, request: Request, user: Me, db: Db) -> TicketOut:
    account = _account(db, user)
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Choose what the problem is about.")
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
    )
    db.add(ticket)
    db.commit()

    s: Settings = request.app.state.settings
    mailer: Mailer = request.app.state.mailer
    who = f"{account.name} (@{account.username}, {account.role}) <{account.email}>"
    try:
        inbox = _inbox(s)
        if inbox:
            mailer.send(
                inbox,
                f"[{ticket.number}] {CATEGORIES[ticket.category]}: {subject}",
                f"New support complaint {ticket.number}\n\nFrom: {who}\n"
                f"Category: {CATEGORIES[ticket.category]}\n"
                f"Where: {ticket.page or 'not given'}\n\n{message}\n\n"
                "Reply to this email to answer the user directly.",
                reply_to=account.email,
            )
            ticket.emailed = True
        mailer.send(
            account.email,
            f"We received your complaint {ticket.number}",
            f"Hi {account.name},\n\nThank you for telling us. Your complaint has the number "
            f"{ticket.number}:\n\n{subject}\n\n{message}\n\nThe Mentora team will reply to this "
            f"email address. If you want to add something, write to {inbox or 'us'} and mention "
            f"{ticket.number}.",
        )
    except MailError:
        log.warning("support email for %s failed", ticket.number, exc_info=True)
    db.commit()
    return _out(ticket)
