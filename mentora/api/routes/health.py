from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mentora import SCHEMA_VERSION, __version__
from mentora.api.deps import db_session
from mentora.config.settings import Settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    app: str
    version: str
    schema_version: str
    mode: str
    llm_backend: str
    database: str


@router.get("/health")
def health(request: Request, db: Annotated[Session, Depends(db_session)]) -> Health:
    settings: Settings = request.app.state.settings
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "unreachable"
    return Health(
        status="ok" if database == "ok" else "degraded",
        app=settings.app.name,
        version=__version__,
        schema_version=SCHEMA_VERSION,
        mode=settings.app.mode,
        llm_backend=settings.llm.backend,
        database=database,
    )
