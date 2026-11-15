"""Run the point-in-time historical sanity check and write a JSON report.

Run: uv run python scripts/historical_sanity_check.py [--seasons 2024 2025 2026]
"""

from __future__ import annotations

import argparse
import json
import time

from diski9.db import make_engine
from diski9.screener.sanity import run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competitions", type=int, nargs="+", default=[39, 288])
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--out", default="docs/historical_sanity_check.json")
    args = ap.parse_args()
    t = time.time()
    with make_engine().connect() as conn:
        report = run(conn, args.competitions, args.seasons)
    report["seconds"] = round(time.time() - t, 1)
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "failed_fixtures"}, indent=2))


if __name__ == "__main__":
    main()
