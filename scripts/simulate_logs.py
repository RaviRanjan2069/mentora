"""Generate SIMULATED tutoring logs (debugging and pipeline testing only).

    python scripts/simulate_logs.py --sessions 120 --turns 18 --db mongodb://localhost:27017/mentora_sim

Writes into a separate database by default, so simulated sessions never mix with real
learner data.
"""

from __future__ import annotations

import argparse
import json

from mentora.config import get_settings
from mentora.db import connect
from mentora.offline.simulator import run_simulation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=120)
    ap.add_argument("--turns", type=int, default=18)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--db", default="mongodb://localhost:27017/mentora_sim")
    args = ap.parse_args()
    stats = run_simulation(
        get_settings(),
        connect(args.db),
        n_sessions=args.sessions,
        turns=args.turns,
        seed=args.seed,
    )
    print(json.dumps(stats.as_dict(), indent=2))


if __name__ == "__main__":
    main()
