"""Train the knowledge-tracing models (DKT and AKT-style) and fit the tactic HMM.

    python scripts/train_learner_models.py                       # synthetic sample data
    python scripts/train_learner_models.py --assistments data/assistments/skill_builder.csv
    python scripts/train_learner_models.py --hmm-from-db         # tactics from logged events

Prints held-out-learner AUC for both KT models and the BIC table for the HMM, and saves
models to learner_model.model_dir. Synthetic results are a sanity check, not evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sqlalchemy import select

from mentora.config import get_settings
from mentora.course import load_course
from mentora.db import make_engine, make_session_factory
from mentora.db import models as m
from mentora.learner_model.hmm_tactics import fit_tactic_hmm
from mentora.learner_model.kt.data import load_assistments, synthetic_sequences
from mentora.learner_model.kt.train import save_model, train_kt
from mentora.learner_model.tactics import TACTIC_INDEX, code_statement
from mentora.logging_xapi.statements import Statement


def synthetic_tactics(n: int, length: int, seed: int) -> list[list[int]]:
    """Three latent study modes (planning, practising, help-seeking) for sanity checks."""
    rng = np.random.default_rng(seed)
    emit = np.array(
        [
            [0.30, 0.05, 0.05, 0.40, 0.10, 0.10],  # planning: PLAN, READ
            [0.15, 0.60, 0.05, 0.05, 0.05, 0.10],  # practising: QUIZ
            [0.10, 0.15, 0.50, 0.05, 0.15, 0.05],  # help-seeking: HINT, CHAT
        ]
    )
    trans = np.array([[0.7, 0.25, 0.05], [0.05, 0.8, 0.15], [0.05, 0.45, 0.5]])
    seqs = []
    for _ in range(n):
        s, seq = 0, []
        for _t in range(length):
            seq.append(int(rng.choice(6, p=emit[s])))
            s = int(rng.choice(3, p=trans[s]))
        seqs.append(seq)
    return seqs


def tactics_from_db() -> list[list[int]]:
    factory = make_session_factory(make_engine())
    with factory() as db:
        rows = db.execute(
            select(m.Event.session_id, m.Event.statement).order_by(
                m.Event.session_id, m.Event.timestamp
            )
        ).all()
    by_session: dict[str | None, list[int]] = {}
    for sid, raw in rows:
        tactic = code_statement(Statement.model_validate(raw))
        if tactic is not None:
            by_session.setdefault(sid, []).append(TACTIC_INDEX[tactic])
    return [s for s in by_session.values() if len(s) >= 3]


def main() -> None:
    settings = get_settings()
    cfg = settings.learner_model
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assistments", type=Path, default=None)
    ap.add_argument("--learners", type=int, default=300)
    ap.add_argument("--length", type=int, default=60)
    ap.add_argument("--hmm-from-db", action="store_true")
    args = ap.parse_args()

    if args.assistments:
        seqs, skills = load_assistments(args.assistments)
        n_concepts, source = len(skills), f"ASSISTments ({args.assistments.name})"
    else:
        course = load_course(settings.app.concepts_file)
        seqs = synthetic_sequences(course, args.learners, args.length, cfg.kt_seed)
        n_concepts, source = len(course.concepts), "synthetic (sanity check only)"

    print(f"Knowledge tracing on {source}: {len(seqs)} learners, {n_concepts} concepts")
    results = {}
    for kind in ("dkt", "akt"):
        model, report = train_kt(kind, seqs, n_concepts, cfg)
        path = save_model(model, report, cfg.model_dir, cfg.kt_hidden, cfg.kt_heads)
        results[kind] = report.test_auc
        print(
            f"  {kind.upper():4} held-out AUC {report.test_auc:.3f}  accuracy "
            f"{report.test_accuracy:.3f}  ({report.n_test_learners} test learners) -> {path}"
        )

    tactic_seqs = tactics_from_db() if args.hmm_from_db else synthetic_tactics(200, 40, cfg.kt_seed)
    hmm, bic = fit_tactic_hmm(
        tactic_seqs,
        cfg.hmm_states_min,
        cfg.hmm_states_max,
        cfg.hmm_iterations,
        cfg.kt_seed,
        cfg.hmm_restarts,
    )
    hmm_path = cfg.model_dir / "tactic_hmm.json"
    hmm.save(hmm_path)
    print(
        "Tactic HMM BIC by number of states: "
        + ", ".join(f"H={h}: {v:.0f}" for h, v in bic.items())
    )
    print(f"  chose H={hmm.n_states} -> {hmm_path}")
    (cfg.model_dir / "learner_models_report.json").write_text(
        json.dumps(
            {"source": source, "auc": results, "hmm_bic": bic, "hmm_states": hmm.n_states}, indent=2
        )
    )


if __name__ == "__main__":
    main()
