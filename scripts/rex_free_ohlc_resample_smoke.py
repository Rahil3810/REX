"""Real-data smoke: free OHLC → Bars → M1..D1 resample report."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from research.free_ohlc.dataset import adapter_stats_to_dict, build_research_dataset
from research.free_ohlc.resampler import SUPPORTED_TIMEFRAMES

REPORT_PATH = Path("/tmp/rex_free_ohlc_resample.json")
DEFAULT_CSV = Path("research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Free OHLC research resample smoke")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default="2026-01-05")
    p.add_argument("--end", default="2026-01-07")
    p.add_argument(
        "--skip-invalid-ohlc",
        action="store_true",
        default=True,
        help="Drop invalid OHLC rows (default True for real Kaggle sample)",
    )
    p.add_argument(
        "--no-skip-invalid-ohlc",
        action="store_true",
        help="Reject invalid OHLC instead of dropping",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Emit partial HTF buckets (default False)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    skip = not args.no_skip_invalid_ohlc

    report: dict[str, object] = {
        "source_file": str(args.csv),
        "symbol": args.symbol,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "skip_invalid_ohlc": skip,
        "allow_partial": bool(args.allow_partial),
        "overall_result": "FAILED",
        "error": None,
    }

    try:
        ds = build_research_dataset(
            args.csv,
            symbol=args.symbol,
            start=start,
            end=end,
            skip_invalid_ohlc=skip,
            target_timeframes=SUPPORTED_TIMEFRAMES,
            allow_partial=bool(args.allow_partial),
        )
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    frames: dict[str, object] = {}
    for tf, result in ds.resamples.items():
        st = result.stats
        frames[tf] = {
            "bar_count": st.emitted_bar_count,
            "first_timestamp": (
                st.first_timestamp.isoformat(sep=" ") if st.first_timestamp else None
            ),
            "last_timestamp": (
                st.last_timestamp.isoformat(sep=" ") if st.last_timestamp else None
            ),
            "skipped_incomplete_buckets": st.skipped_incomplete_buckets,
            "skipped_closed_buckets": st.skipped_closed_buckets,
            "completeness_rule": st.completeness_rule,
        }

    report.update(
        {
            "provenance": ds.provenance,
            "adapter_stats": adapter_stats_to_dict(ds.adapter.stats),
            "m1_coverage": {
                "accepted": ds.adapter.stats.rows_accepted,
                "dropped_invalid": ds.adapter.stats.rows_dropped_invalid,
                "first_timestamp": (
                    ds.adapter.stats.first_timestamp.isoformat(sep=" ")
                    if ds.adapter.stats.first_timestamp
                    else None
                ),
                "last_timestamp": (
                    ds.adapter.stats.last_timestamp.isoformat(sep=" ")
                    if ds.adapter.stats.last_timestamp
                    else None
                ),
            },
            "timeframes": frames,
            "volume_semantics": ds.adapter.stats.volume_type,
            "resampling_method": ds.provenance.get("resampler_version"),
            "overall_result": "SUCCESS" if ds.adapter.stats.bar_count > 0 else "FAILED",
        }
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=== REX FREE OHLC RESAMPLE SMOKE ===")
    print(f"source_file: {report['source_file']}")
    print(f"range: {start} .. {end}")
    print(f"m1_accepted: {ds.adapter.stats.rows_accepted}")
    print(f"m1_dropped_invalid: {ds.adapter.stats.rows_dropped_invalid}")
    print(f"volume_type: {ds.adapter.stats.volume_type}")
    print(f"timezone_policy: {ds.adapter.stats.timezone_policy}")
    for tf in SUPPORTED_TIMEFRAMES:
        info = frames[tf]
        print(
            f"{tf}: bars={info['bar_count']} "
            f"first={info['first_timestamp']} last={info['last_timestamp']} "
            f"incomplete_skipped={info['skipped_incomplete_buckets']}"
        )
    print(f"overall_result: {report['overall_result']}")
    print(f"wrote {REPORT_PATH}")
    return 0 if report["overall_result"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
