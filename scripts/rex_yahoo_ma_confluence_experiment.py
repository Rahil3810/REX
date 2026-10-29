"""CLI: observational Yahoo EURUSD H1 MA Confluence V1 experiments (7D + 1M).

Does not modify MA Confluence parameters or run S002.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from research.yahoo.ma_confluence_experiment import (
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    format_experiment_summary,
    run_both_yahoo_experiments,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Yahoo EURUSD H1 MA Confluence V1 observational experiment"
    )
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    result_7d, result_1m = run_both_yahoo_experiments(
        output_dir=args.output_dir,
        data_dir=args.data_dir,
    )
    print(format_experiment_summary(result_7d))
    print(format_experiment_summary(result_1m))

    qa7 = result_7d.quality_audit
    qa1 = result_1m.quality_audit
    print("=== DATA QUALITY (shared fetch / combined bars) ===")
    print(f"7D audit rows: {qa7.get('total_h1_rows')}")
    print(f"1M audit rows: {qa1.get('total_h1_rows')}")
    print(f"duplicates: {qa7.get('duplicate_timestamps')}")
    print(f"missing H1 buckets (approx): {qa7.get('missing_h1_buckets')}")
    print(f"invalid OHLC: {qa7.get('invalid_ohlc_candles')}")
    print(f"flat candles: {qa7.get('flat_candles')}")
    print(f"zero-volume: {qa7.get('zero_volume_candles')}")
    print(f"weekend candles: {qa7.get('weekend_candles')}")
    print(f"chronological: {qa7.get('chronological')}")
    print(f"continuity gaps: {qa7.get('ohlc_continuity_gaps')}")
    print(f"filtered notes: {qa7.get('filtered_count')}")
    if qa7.get("filter_reasons"):
        for reason in qa7["filter_reasons"][:20]:
            print(f"  - {reason}")
    print()
    print("Config locked: MA Confluence V1 defaults unchanged.")
    print("S002 was NOT modified or executed.")
    print(f"wrote {args.output_dir / 'yahoo_eurusd_7d.json'}")
    print(f"wrote {args.output_dir / 'yahoo_eurusd_1m.json'}")
    print(f"wrote {args.data_dir / 'EURUSD_H1_latest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
