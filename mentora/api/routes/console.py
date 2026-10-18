"""Teacher console API, part 2: class overview, students, system status, content
management (course material upload, quiz items), model training and reports."""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from mentora.analytics import class_overview, student_detail, students_summary
from mentora.api.deps import User, db_session, orchestrator, require_teacher
from mentora.config.settings import Settings
from mentora.course import item_concept_keys
from mentora.db import ASC, Store
from mentora.db import models as m
from mentora.orchestrator.turn import Orchestrator
from mentora.rag.embeddings import make_embedder
from mentora.rag.ingest import (
    TEXT_SUFFIXES,
    PassageDraft,
    build_passages,
    embed_passages,
    load_documents,
    store_passages,
)

router = APIRouter(prefix="/api/teacher", tags=["teacher-console"])
Teacher = Annotated[User, Depends(require_teacher)]
Db = Annotated[Store, Depends(db_session)]
Orch = Annotated[Orchestrator, Depends(orchestrator)]

UPLOAD_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".pptx", ".yaml", ".yml"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/overview")
def overview(user: Teacher, db: Db, orch: Orch) -> dict[str, Any]:
    return class_overview(db, orch, orch.clock())


@router.get("/students")
def students(user: Teacher, db: Db, orch: Orch) -> list[dict[str, Any]]:
    return students_summary(db, orch, orch.clock())


@router.get("/students/{learner_id}")
def student(learner_id: str, user: Teacher, db: Db, orch: Orch) -> dict[str, Any]:
    data = student_detail(db, orch, learner_id, orch.clock())
    if data is None:
        raise HTTPException(404, "No such student")
    return data


def _local_llm_status(s: Settings) -> tuple[str, str]:
    """Ask the local model server (e.g. Ollama) whether it is up and has the model."""
    import httpx

    where = f"{s.llm.local_model} at {s.local_llm_base_url}"
    if s.llm.backend != "local":
        return "configured", where
    try:
        key = s.local_llm_api_key.get_secret_value()
        resp = httpx.get(
            f"{s.local_llm_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=5.0,  # a remote model server (tunnel) needs longer than 1.5 s
        )
        names = {m.get("id") for m in resp.json().get("data", [])}
    except Exception:
        return "down", f"{where}: not reachable (is Ollama running?)"
    if s.llm.local_model not in names:
        return "down", f"{where}: model not downloaded (ollama pull {s.llm.local_model})"
    return "running", where


@router.get("/status")
def status(request: Request, user: Teacher, db: Db, orch: Orch) -> list[dict[str, str]]:
    """Honest component status: only what can be checked cheaply, without paid calls."""
    s: Settings = request.app.state.settings
    out = [{"name": "API server", "state": "running", "detail": "responding"}]
    try:
        db.db.command("ping")
        out.append({"name": "Database", "state": "running", "detail": "MongoDB"})
    except Exception as exc:
        out.append({"name": "Database", "state": "down", "detail": str(exc)[:80]})
    if s.jobs.mode == "inline":
        out.append(
            {"name": "Background jobs", "state": "running", "detail": "inline in the API process"}
        )
    else:
        try:
            from mentora.worker import celery_app

            alive = celery_app.control.ping(timeout=1.0)
            out.append(
                {
                    "name": "Background worker",
                    "state": "running" if alive else "down",
                    "detail": f"{len(alive)} worker(s)" if alive else "no reply",
                }
            )
        except Exception as exc:
            out.append({"name": "Background worker", "state": "down", "detail": str(exc)[:80]})
    llm = {
        "offline": ("running", "offline templates (no AI model)"),
        "fake": ("running", "test stub"),
        "hosted": ("configured", s.llm.hosted_model),
        "local": _local_llm_status(s),
    }[s.llm.backend]
    out.append({"name": "LLM service", "state": llm[0], "detail": llm[1]})
    n = db.count(m.CorpusPassage, {"course_id": orch.course_id})
    store = "MongoDB + in-memory index"
    out.append(
        {
            "name": "Vector store",
            "state": "running" if n else "empty",
            "detail": f"{n} passages, {store}, {s.rag.embedder}",
        }
    )
    return out


# --- content management ----------------------------------------------------------------------


@router.get("/materials")
def materials(user: Teacher, db: Db, orch: Orch) -> list[dict[str, Any]]:
    grouped: dict[str | None, list[int | None]] = {}
    for source, week in db.values(
        m.CorpusPassage, ["source_file", "week"], {"course_id": orch.course_id}
    ):
        grouped.setdefault(source, []).append(week)
    rows = [  # (source_file, passages, earliest week) like SQL GROUP BY with MIN
        (source, len(weeks), min((w for w in weeks if w is not None), default=None))
        for source, weeks in grouped.items()
    ]
    files: dict[str, dict[str, Any]] = {}
    for source, n, week in rows:
        name = (source or "unknown").split("#", 1)[0]
        f = files.setdefault(name, {"source": name, "passages": 0, "week": week})
        f["passages"] += n
    return sorted(files.values(), key=lambda f: (f["week"] or 99, f["source"]))


@router.post("/materials")
async def upload_material(
    file: UploadFile, request: Request, user: Teacher, orch: Orch
) -> dict[str, Any]:
    """Ingest one file (md, txt, pdf, pptx or FAQ yaml). Instruction-like passages are
    quarantined and reported, never stored."""
    name = Path(file.filename or "upload").name
    if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
        raise HTTPException(415, f"Unsupported file type; use one of {sorted(UPLOAD_SUFFIXES)}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20 MB)")
    s: Settings = request.app.state.settings
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        try:
            docs = load_documents(path)
        except Exception as exc:
            raise HTTPException(422, f"Could not read the file: {exc}") from exc
    quarantined: list[PassageDraft] = []
    drafts = build_passages(
        docs, orch.course, s.rag.chunk_tokens, s.rag.chunk_overlap_tokens, quarantined
    )
    if not drafts and not quarantined:
        raise HTTPException(422, "No text found in the file")
    n = store_passages(orch.factory, orch.course_id, embed_passages(drafts, make_embedder(s)))
    orch.refresh_rag()
    request.app.state.rag_pipeline = None
    return {
        "source": name,
        "passages": n,
        "quarantined": [{"text": q.text[:200]} for q in quarantined],
    }


@router.delete("/materials/{source}", status_code=204)
def delete_material(source: str, request: Request, user: Teacher, db: Db, orch: Orch) -> None:
    deleted = db.delete_many(
        m.CorpusPassage,
        {
            "course_id": orch.course_id,
            "$or": [
                {"source_file": source},
                {"source_file": {"$regex": f"^{re.escape(source)}#"}},
            ],
        },
    )
    if not deleted:
        raise HTTPException(404, "No material from that file")
    db.commit()
    orch.refresh_rag()
    request.app.state.rag_pipeline = None


class TeacherItemOut(BaseModel):
    id: int
    external_id: str | None
    text: str
    item_type: str
    graded: bool
    answer_key: str | None
    concepts: list[str]


@router.get("/items")
def items(user: Teacher, db: Db, orch: Orch) -> list[TeacherItemOut]:
    keys = item_concept_keys(db, orch.course_id)
    return [
        TeacherItemOut(
            id=i.id,
            external_id=i.external_id,
            text=i.text,
            item_type=i.item_type,
            graded=i.graded,
            answer_key=i.answer_key,
            concepts=keys.get(i.id, []),
        )
        for i in db.find(m.Item, {"course_id": orch.course_id}, sort=[("id", ASC)])
    ]


# --- model training -------------------------------------------------------------------------


@router.post("/policies/train")
def train_policy(request: Request, user: Teacher, orch: Orch) -> dict[str, Any]:
    """Run the offline loop now. A result can only ever be a candidate awaiting approval."""
    from mentora.offline.train import run_offline_pipeline

    s: Settings = request.app.state.settings
    result = run_offline_pipeline(s, orch.factory, data_label="logged sessions")
    return {"status": result.status, "version": result.version, "reasons": result.reasons}


@router.get("/models")
def models(request: Request, user: Teacher) -> dict[str, Any]:
    s: Settings = request.app.state.settings
    d = s.learner_model.model_dir
    report = d / "learner_models_report.json"
    return {
        "mastery_model": s.learner_model.mastery_model,
        "kt_models": sorted(p.name for p in d.glob("kt_*.pt")) if d.exists() else [],
        "tactic_hmm": (d / "tactic_hmm.json").exists(),
        "report": json.loads(report.read_text()) if report.exists() else None,
    }


# --- reports ----------------------------------------------------------------------------------


@router.get("/reports/class.csv")
def class_csv(user: Teacher, db: Db, orch: Orch) -> Response:
    rows = students_summary(db, orch, orch.clock())
    buf = io.StringIO()
    fields = [
        "learner",
        "simulated",
        "sessions",
        "last_active",
        "mean_mastery",
        "quiz_average",
        "answers",
        "dropout_risk",
        "at_risk",
        "open_escalations",
    ]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in fields})
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mentora_class.csv"},
    )
