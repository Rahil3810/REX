"""CLI: baseline Automatic Zone V1 vs V1_WIDTH_FILTER controlled experiment."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from research.width_filter_experiment import (
    PREDECLARED_MIN_WIDTH_ATR_RATIO,
    WidthFilterExperimentConfig,
    run_width_filter_experiment,
)

REPORT_PATH = Path("/tmp/rex_width_filter_experiment.json")
DEFAULT_CSV = Path("research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="REX width-filter experiment (baseline V1 vs V1_WIDTH_FILTER)"
    )
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default=None, help="YYYY-MM-DD (default: dataset bounds)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (default: dataset bounds)")
    p.add_argument("--timeframe", default="M15")
    p.add_argument(
        "--min-width-atr",
        type=float,
        default=PREDECLARED_MIN_WIDTH_ATR_RATIO,
        help="Predeclared minimum width/causal_ATR at creation (default: 0.35)",
    )
    p.add_argument("--report", type=Path, default=REPORT_PATH)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    config = WidthFilterExperimentConfig(min_width_atr_ratio=args.min_width_atr)
    result = run_width_filter_experiment(
        args.csv,
        symbol=args.symbol,
        start=start,
        end=end,
        timeframe=args.timeframe,
        config=config,
    )
    payload = result.to_dict()
    args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    fw = result.full_window
    b, e = fw["baseline"], fw["experiment"]
    print("=== REX WIDTH FILTER EXPERIMENT ===")
    print(f"source: {result.source_path}")
    print(f"window: {result.effective_start} .. {result.effective_end}")
    print(f"threshold: {config.min_width_atr_ratio} (predeclared)")
    print("--- FULL WINDOW ---")
    print(
        f"baseline: zones={b['total_zones']} ix={b['total_interactions']} "
        f"success={b['success_rate']} failure={b['failure_rate']} "
        f"broken={b['broken_rate']} median_w/atr={b['median_width_atr']}"
    )
    print(
        f"experiment: zones={e['total_zones']} rejected={e['zones_rejected_by_width_filter']} "
        f"ix={e['total_interactions']} success={e['success_rate']} "
        f"failure={e['failure_rate']} broken={e['broken_rate']} "
        f"zone_ret={e['zone_retention_pct']} ix_ret={e['interaction_retention_pct']}"
    )
    print(f"delta broken: {fw['comparison']['broken_rate_delta']}")
    print("--- THIRDS ---")
    for row in result.chronological_thirds:
        if "baseline" not in row or "total_zones" not in row["baseline"]:
            continue
        rb, re = row["baseline"], row["experiment"]
        print(
            f"{row['label']}: base_z={rb['total_zones']} exp_z={re['total_zones']} "
            f"rejected={re.get('zones_rejected_by_width_filter')} "
            f"base_br={rb.get('broken_rate')} exp_br={re.get('broken_rate')} "
            f"zone_ret={re.get('zone_retention_pct')} ix_ret={re.get('interaction_retention_pct')}"
        )
    print(f"classification: {result.classification['classification_code']}")
    print(f"answer: {result.classification['answers_research_question']}")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
