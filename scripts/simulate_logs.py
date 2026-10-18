"""Generate SIMULATED tutoring logs (debugging and pipeline testing only).

    python scripts/simulate_logs.py --sessions 120 --turns 18 --db sqlite:///./simulated.db

Writes into a separate database by default, so simulated sessions never mix with real
learner data.
"""

from __future__ import annotations

import argparse
import json

from mentora.config import get_settings
from mentora.db import Base, make_engine, make_session_factory
from mentora.offline.simulator import run_simulation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=120)
    ap.add_argument("--turns", type=int, default=18)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--db", default="sqlite:///./simulated.db")
    args = ap.parse_args()
    engine = make_engine(args.db)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    stats = run_simulation(
        get_settings(),
        make_session_factory(engine),
        n_sessions=args.sessions,
        turns=args.turns,
        seed=args.seed,
    )
    print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
    main()
