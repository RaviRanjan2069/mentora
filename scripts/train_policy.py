"""Run the offline loop: dataset -> candidate -> OPE -> fairness -> simulation check -> gate.

    python scripts/train_policy.py                          # logged sessions in the main DB
    python scripts/train_policy.py --db sqlite:///./simulated.db --label simulation
    python scripts/train_policy.py --method tabular

The result is registered in the policy registry ('candidate' awaiting teacher approval,
or 'rejected' with reasons) and the teacher report is written to reports/.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mentora.config import get_settings
from mentora.db import make_engine, make_session_factory
from mentora.offline.train import run_offline_pipeline


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=settings.database_url)
    ap.add_argument("--method", choices=["cql_ensemble", "tabular"], default=None)
    ap.add_argument("--label", default="logged sessions")
    ap.add_argument("--out", type=Path, default=Path("reports"))
    args = ap.parse_args()
    result = run_offline_pipeline(
        settings,
        make_session_factory(make_engine(args.db)),
        method=args.method,
        data_label=args.label,
    )
    print(f"status: {result.status}  version: {result.version}")
    for r in result.reasons:
        print(f"  - {r}")
    if result.report_markdown:
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"policy_{result.version}.md"
        path.write_text(result.report_markdown, encoding="utf-8")
        print(f"teacher report: {path}")


if __name__ == "__main__":
    main()
