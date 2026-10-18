"""Load test against a running Mentora server (dev login must be on).

    python scripts/load_test.py --url http://127.0.0.1:8000 --learners 30 --workers 10

Each simulated learner signs in, starts a session, sets a goal, answers practice items,
asks for hints and ends the session. Prints latency percentiles and errors. SQLite
serialises writes, so run serious load tests against PostgreSQL (docker compose).
"""

from __future__ import annotations

import argparse
import json

import httpx

from mentora.loadtest import run_load


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--learners", type=int, default=30)
    ap.add_argument("--messages", type=int, default=4)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    result = run_load(
        lambda: httpx.Client(base_url=args.url, timeout=120),
        args.learners,
        args.messages,
        args.workers,
    )
    print(json.dumps(result.summary(), indent=2))
    for e in result.errors[:20]:
        print("ERROR", e)


if __name__ == "__main__":
    main()
