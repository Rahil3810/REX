"""CLI smoke: free OHLC → HTF → Automatic Zone V1 → Zone Evaluation V1.

Research only. Does not write to data/historical/ or touch live trading.

If --start/--end are omitted, uses the actual dataset first/last dates.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from research.zones_pipeline import (
    DEFAULT_EVAL_TIMEFRAMES,
    DEFAULT_TIMEFRAMES,
    run_research_zones_smoke,
)

REPORT_PATH = Path("/tmp/rex_research_zones_smoke.json")
DEFAULT_CSV = Path("research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="REX research zones smoke (V1)")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument(
        "--start",
        default=None,
        help="Inclusive start YYYY-MM-DD (default: dataset first date)",
    )
    p.add_argument(
        "--end",
        default=None,
        help="Inclusive end YYYY-MM-DD (default: dataset last date)",
    )
    p.add_argument(
        "--timeframes",
        nargs="+",
        default=list(DEFAULT_EVAL_TIMEFRAMES),
        help=f"HTF labels (default: {' '.join(DEFAULT_EVAL_TIMEFRAMES)}; "
        f"minimum recommended: {' '.join(DEFAULT_TIMEFRAMES)})",
    )
    p.add_argument(
        "--no-skip-invalid-ohlc",
        action="store_true",
        help="Reject invalid OHLC instead of dropping",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow partial HTF buckets when resampling",
    )
    p.add_argument(
        "--no-segment-stability",
        action="store_true",
        help="Skip first/middle/final third stability comparison",
    )
    p.add_argument(
        "--no-structure-context",
        action="store_true",
        help="Skip M15 structure-context diagnostic experiment",
    )
    p.add_argument(
        "--no-geometry-lifecycle",
        action="store_true",
        help="Skip M15 geometry/lifecycle diagnostic experiment",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=REPORT_PATH,
        help="Output JSON path",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    result = run_research_zones_smoke(
        args.csv,
        symbol=args.symbol,
        start=start,
        end=end,
        timeframes=tuple(args.timeframes),
        skip_invalid_ohlc=not args.no_skip_invalid_ohlc,
        allow_partial=bool(args.allow_partial),
        include_segment_stability=not args.no_segment_stability,
        include_structure_context=not args.no_structure_context,
        include_geometry_lifecycle=not args.no_geometry_lifecycle,
    )
    payload = result.to_dict()
    payload["overall_result"] = (
        "SUCCESS"
        if any(r.bar_count > 0 for r in result.by_timeframe.values())
        else "FAILED"
    )

    args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("=== REX RESEARCH ZONES SMOKE ===")
    print(f"source: {result.source_path}")
    print(
        f"requested: {result.requested_start} .. {result.requested_end} "
        f"(None = dataset bounds)"
    )
    print(f"effective: {result.effective_start} .. {result.effective_end}")
    print(
        f"m1_accepted: {result.dataset_bounds.accepted_m1_bars} "
        f"dropped_invalid: {result.dataset_bounds.dropped_invalid_bars} "
        f"volume_type: {result.dataset_bounds.volume_type}"
    )
    print(f"symbol: {result.symbol}")
    for tf, tr in result.by_timeframe.items():
        print(
            f"{tf}: bars={tr.bar_count} swings={tr.swing_count} "
            f"zones={len(tr.zones)} "
            f"supply={sum(1 for z in tr.zones if z.zone.kind and z.zone.kind.value=='supply')} "
            f"demand={sum(1 for z in tr.zones if z.zone.kind and z.zone.kind.value=='demand')} "
            f"ix={tr.report.get('interaction_count')} "
            f"success_rate={tr.report.get('success_rate')} "
            f"broken_rate={tr.report.get('broken_rate')}"
        )
    print(f"summary_zones_generated: {result.summary['zones_generated']}")
    print(f"summary_success_rate: {result.summary['success_rate']}")
    print(f"research_classification: {result.research_classification}")
    if result.structure_context_experiment:
        diag = result.structure_context_experiment.get("diagnosis", {})
        print(f"structure_context_conclusion: {diag.get('conclusion_code')}")
    if result.geometry_lifecycle_experiment:
        diag = result.geometry_lifecycle_experiment.get("diagnosis", {})
        print(f"geometry_lifecycle_conclusion: {diag.get('conclusion_code')}")
        print(f"geometry_lifecycle_answer: {diag.get('answers_research_question')}")
        agg = result.geometry_lifecycle_experiment.get("aggregates", {})
        for name in ("by_width_over_atr", "by_age_to_first_interaction", "by_zone_kind"):
            block = agg.get(name, {})
            for bucket, metrics in block.items():
                ss = metrics.get("sample_size", {})
                print(
                    f"  {name}/{bucket}: zones={metrics.get('zone_count')} "
                    f"ix={metrics.get('interaction_count')} "
                    f"broken={metrics.get('broken_rate')} "
                    f"success={metrics.get('success_rate')} "
                    f"too_small={ss.get('too_small_to_interpret')}"
                )
    print(f"classification_rationale: {result.classification_rationale}")
    print(f"deterministic_hash: {result.deterministic_hash}")
    print(f"overall_result: {payload['overall_result']}")
    print(f"wrote {args.report}")
    return 0 if payload["overall_result"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
