"""CLI: export MA Confluence Zone V1 candidates for manual review.

Research only. Fixed V1 config for the first frozen validation batch.
Default: EURUSD H1.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from core.zones.auto.ma_confluence import MAConfluenceZoneConfig
from research.ma_confluence_pipeline import (
    run_ma_confluence_pipeline,
    write_candidates_csv,
    write_candidates_json,
)

DEFAULT_CSV = Path("research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv")
DEFAULT_JSON = Path("/tmp/rex_ma_confluence_candidates.json")
DEFAULT_CSV_OUT = Path("/tmp/rex_ma_confluence_candidates.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="REX MA Confluence Zone V1 candidate export (research)"
    )
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="H1")
    p.add_argument("--start", default=None, help="YYYY-MM-DD")
    p.add_argument("--end", default=None, help="YYYY-MM-DD")
    p.add_argument("--report-json", type=Path, default=DEFAULT_JSON)
    p.add_argument("--report-csv", type=Path, default=DEFAULT_CSV_OUT)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    config = MAConfluenceZoneConfig()  # frozen V1 defaults

    result = run_ma_confluence_pipeline(
        args.csv,
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=start,
        end=end,
        config=config,
    )
    write_candidates_json(result, args.report_json)
    write_candidates_csv(result, args.report_csv)

    print("=== REX MA CONFLUENCE CANDIDATES ===")
    print(f"source: {result.source_path}")
    print(f"window: {result.effective_start} .. {result.effective_end}")
    print(f"timeframe: {result.timeframe}")
    print(f"bars: {result.bar_count}")
    print(f"candidates: {len(result.candidates)}")
    print(
        f"config: k_enter={config.k_enter} k_exit={config.k_exit} "
        f"min_persist={config.min_persist} exit_persist={config.exit_persist}"
    )
    print("EMA200: evidence-only (not a gate)")
    print(
        "Research Q-A only for this export. Do not retune on this sample. "
        "S002 edge (Q-B) is deferred."
    )
    print(f"wrote {args.report_json}")
    print(f"wrote {args.report_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
