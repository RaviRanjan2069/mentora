"""Lambda-sensitivity of the reward (simulation - debugging only).

Runs simulated sessions, records every reward term, then recomputes session returns with
each lambda weight halved and doubled. Reports how much the mean return moves and how well
the ranking of sessions is preserved (Spearman). A weight whose change reorders sessions a
lot is one the team should set with care.

    python scripts/reward_sensitivity.py --sessions 60
"""

from __future__ import annotations

import argparse
from collections import defaultdict

import numpy as np
from scipy.stats import spearmanr

from mentora.config import get_settings
from mentora.db import connect
from mentora.db.client import drop_mock
from mentora.offline.simulator import LABEL, run_simulation
from mentora.reward.reward import RewardTerms

WEIGHTS = ("lambda_k", "lambda_s", "lambda_g", "lambda_d", "lambda_l")
TERM = {
    "lambda_k": "delta_k",
    "lambda_s": "r_srl",
    "lambda_g": "r_goal",
    "lambda_d": "r_dep",
    "lambda_l": "r_load",
}
SIGN = {"lambda_k": 1, "lambda_s": 1, "lambda_g": 1, "lambda_d": -1, "lambda_l": -1}


def returns(per_session: dict[str, list[RewardTerms]], w: dict[str, float]) -> np.ndarray:
    out = []
    for terms in per_session.values():
        total = 0.0
        for t in terms:
            total += sum(SIGN[k] * w[k] * getattr(t, TERM[k]) for k in WEIGHTS) - t.cost
        out.append(total)
    return np.asarray(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--turns", type=int, default=16)
    args = ap.parse_args()
    settings = get_settings()
    url = "mongomock://reward_sensitivity"  # in memory: simulated data never persists
    drop_mock(url)
    sink: list[tuple[str, int, RewardTerms]] = []
    run_simulation(
        settings,
        connect(url),
        n_sessions=args.sessions,
        turns=args.turns,
        seed=5,
        reward_terms=sink,
    )
    per: dict[str, list[RewardTerms]] = defaultdict(list)
    for sid, _t, terms in sink:
        per[sid].append(terms)
    base_w = {k: getattr(settings.reward, k) for k in WEIGHTS}
    base = returns(per, base_w)
    print(f"Reward lambda-sensitivity - {LABEL}")
    print(f"{len(per)} sessions; baseline mean return {base.mean():+.3f}\n")
    header = ["x0.5 mean", "x2 mean", "rank corr x0.5", "rank corr x2"]
    print(f"{'weight':<10} " + " ".join(f"{h:>15}" for h in header))
    for k in WEIGHTS:
        row = []
        for f in (0.5, 2.0):
            r = returns(per, {**base_w, k: base_w[k] * f})
            rho = spearmanr(base, r).statistic if np.std(r) > 0 and np.std(base) > 0 else 1.0
            row.append((r.mean(), rho))
        cells = [f"{row[0][0]:+.3f}", f"{row[1][0]:+.3f}", f"{row[0][1]:.3f}", f"{row[1][1]:.3f}"]
        print(f"{k:<10} " + " ".join(f"{c:>15}" for c in cells))


if __name__ == "__main__":
    main()
