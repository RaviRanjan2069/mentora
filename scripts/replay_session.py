"""Replay a scripted session through the full tutoring turn and print each decision.

    python scripts/replay_session.py data/sample/sessions/demo_session.yaml

Uses the configured database and LLM back-end (MENTORA_LLM__BACKEND=offline needs no key).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from mentora.config import get_settings
from mentora.db import make_engine, make_session_factory
from mentora.db import models as m
from mentora.orchestrator.replay import replay
from mentora.orchestrator.session import build_orchestrator


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("script", type=Path)
    ap.add_argument("--learner", default="lrn_replay_demo")
    args = ap.parse_args()

    settings = get_settings()
    factory = make_session_factory(make_engine())
    orch = build_orchestrator(settings, factory)
    session_id, log = replay(orch, factory, args.script, args.learner)
    with factory() as db:
        rows = {
            t.t: t
            for t in db.scalars(select(m.Transition).where(m.Transition.session_id == session_id))
        }
    print(f"session {session_id}  policy {orch.policy.version}\n")
    for trigger, r in log:
        tr = rows[r.turn]
        reward = "-" if tr.reward is None else f"{tr.reward:+.3f}"
        print(
            f"t={r.turn:<2} {trigger[:48]:<48} -> {r.action_id:<42} "
            f"mu={r.propensity:.3f} r={reward}"
        )
        if r.reply:
            print("     " + r.reply.replace("\n", "\n     ")[:400])
    print(f"\n{len(rows)} transitions; return {sum(t.reward or 0 for t in rows.values()):+.3f}")


if __name__ == "__main__":
    main()
