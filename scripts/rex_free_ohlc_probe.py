"""Research probe: free/public EURUSD OHLC → REX Bar compatibility.

Default source: Kaggle orkadd free EURUSD 1m evaluation sample (UTC ``Z`` timestamps).
Does NOT write to production ``data/historical/``.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, datetime
from pathlib import Path

from historical.bar_contract import build_canonical_bar
from historical.exceptions import HistoricalParseError
from research.free_ohlc.acquire import download_kaggle_orkadd_eurusd_m1_sample
from research.free_ohlc.formats import (
    FreeOhlcBar,
    TimezonePolicy,
    VolumeSemantics,
    load_free_ohlc_csv,
    locate_data_files,
    normalize_symbol,
    ohlc_valid,
)

REPORT_PATH = Path("/tmp/rex_free_ohlc_probe.json")
DEFAULT_DATA_DIR = Path("research/data/free_ohlc/EURUSD/M1")


def _parse_args() -> argparse.Namespace:
    # Small default smoke window inside the Kaggle sample coverage (2026-01..2026-07).
    default_start = date(2026, 1, 5)
    default_end = date(2026, 1, 7)
    p = argparse.ArgumentParser(description="Free OHLC research probe for REX")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--timeframe", default="M1", help="Declared timeframe of the source file")
    p.add_argument("--start", default=default_start.isoformat())
    p.add_argument("--end", default=default_end.isoformat())
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument(
        "--acquire",
        action="store_true",
        help="Download free Kaggle EURUSD M1 sample into --data-dir if missing",
    )
    p.add_argument(
        "--force-acquire",
        action="store_true",
        help="Re-download even if a local CSV already exists",
    )
    p.add_argument(
        "--skip-invalid-ohlc",
        action="store_true",
        help=(
            "Drop bars that fail OHLC integrity instead of failing the probe. "
            "Dropped count is reported; values are never repaired/fabricated."
        ),
    )
    return p.parse_args()


def _parse_iso_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid {flag}={value!r}; expected YYYY-MM-DD") from exc


def analyze_bars(bars: list[FreeOhlcBar]) -> dict[str, object]:
    invalid = 0
    duplicates = 0
    out_of_order = 0
    seen: set[datetime] = set()
    prev: datetime | None = None
    volumes: list[float] = []

    for bar in bars:
        if not ohlc_valid(bar.open, bar.high, bar.low, bar.close):
            invalid += 1
        if bar.timestamp in seen:
            duplicates += 1
        seen.add(bar.timestamp)
        if prev is not None and bar.timestamp < prev:
            out_of_order += 1
        prev = bar.timestamp
        if bar.volume is not None:
            volumes.append(float(bar.volume))

    gaps: list[float] = []
    for a, b in zip(bars, bars[1:]):
        gaps.append((b.timestamp - a.timestamp).total_seconds() / 60.0)

    gap_stats: dict[str, object]
    if gaps:
        gap_stats = {
            "raw_gap_count_gt_1m": sum(1 for g in gaps if g > 1.0001),
            "min_step_minutes": min(gaps),
            "max_step_minutes": max(gaps),
            "median_step_minutes": statistics.median(gaps),
            "gaps_ge_24h": sum(1 for g in gaps if g >= 60 * 24),
            "gaps_gt_5m_lt_24h": sum(1 for g in gaps if 5 < g < 60 * 24),
            "semantics": (
                "Raw consecutive-bar deltas in source-normalized UTC. "
                "Gaps >= 24h are weekend/holiday candidates; gaps >5m and <24h "
                "are suspicious. Not a trading-calendar oracle."
            ),
        }
    else:
        gap_stats = {"raw_gap_count_gt_1m": 0}

    vol_sem = bars[0].volume_semantics.value if bars else VolumeSemantics.NONE.value
    if volumes:
        vol_stats: dict[str, object] = {
            "available": True,
            "semantics": vol_sem,
            "min": min(volumes),
            "max": max(volumes),
            "mean": round(sum(volumes) / len(volumes), 6),
            "zero_count": sum(1 for v in volumes if v == 0),
            "note": (
                "Labeled tick_volume when source provides activity counts; "
                "not assumed exchange-traded volume. Never fabricate."
            ),
        }
    else:
        vol_stats = {
            "available": False,
            "semantics": vol_sem,
            "note": "No volume column / all None — do not fabricate.",
        }

    return {
        "invalid_ohlc_count": invalid,
        "duplicate_timestamp_count": duplicates,
        "out_of_order_count": out_of_order,
        "gap_statistics": gap_stats,
        "volume_statistics": vol_stats,
    }


def try_canonical(symbol: str, bars: list[FreeOhlcBar]) -> dict[str, object]:
    ok = 0
    err = 0
    first_err: str | None = None
    for bar in bars:
        try:
            build_canonical_bar(
                symbol=symbol,
                timestamp=bar.timestamp,  # already naive UTC under documented policy
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
            )
            ok += 1
        except (HistoricalParseError, ValueError) as exc:
            err += 1
            if first_err is None:
                first_err = str(exc)
    return {
        "canonical_bar_compatible": err == 0 and ok == len(bars) and ok > 0,
        "canonical_ok_count": ok,
        "canonical_error_count": err,
        "canonical_first_error": first_err,
    }


def investigation_notes() -> dict[str, object]:
    return {
        "investigated": [
            {
                "name": "Kaggle orkadd EURUSD 1m sample",
                "url": "https://www.kaggle.com/datasets/orkadd/eurusd-1m-ohlcv-forex-historical-data",
                "real_bytes": True,
                "timeframe": "M1",
                "timezone": "UTC (ISO Z)",
                "notes": "Free evaluation sample ~186k M1 bars; full archive is commercial on ork.ad",
            },
            {
                "name": "datahub/datasets exchange-rates daily.csv",
                "url": "https://github.com/datasets/exchange-rates",
                "real_bytes": True,
                "timeframe": "D1 close only (not OHLC)",
                "notes": "Country FX rates, not candle OHLC — weak fit for zones/features",
            },
            {
                "name": "Stooq EURUSD daily",
                "real_bytes": False,
                "notes": "JS/bot wall; no CSV without browser challenge",
            },
            {
                "name": "Yahoo Finance EURUSD=X",
                "real_bytes": False,
                "notes": "Unauthorized without login cookie",
            },
            {
                "name": "Forexite / Gain Capital ratedata",
                "real_bytes": False,
                "notes": "404 / DNS dead",
            },
            {
                "name": "HuggingFace Raihan1234/forex-m1-ohlc",
                "real_bytes": False,
                "notes": "API/resolve returned 401 in this environment",
            },
        ],
        "selected": [
            "kaggle_orkadd_eurusd_m1_sample",
            "epoch_ms_ohlc_local_format (compatibility)",
        ],
    }


def main() -> int:
    args = _parse_args()
    symbol = normalize_symbol(args.symbol)
    timeframe = str(args.timeframe).strip().upper()
    start = _parse_iso_date(args.start, "--start")
    end = _parse_iso_date(args.end, "--end")
    if end < start:
        raise SystemExit("--end must be on or after --start")
    data_dir: Path = args.data_dir

    report: dict[str, object] = {
        "source": None,
        "symbol": symbol,
        "timeframe": timeframe,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "data_dir": str(data_dir),
        "file_name": None,
        "file_size_bytes": None,
        "bar_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "source_format": None,
        "timezone_policy": None,
        "timezone_conversion_applied": False,
        "invalid_ohlc_count": None,
        "duplicate_timestamp_count": None,
        "out_of_order_count": None,
        "gap_statistics": None,
        "volume_statistics": None,
        "canonical_bar_compatible": False,
        "m1_to_htf_derivation_possible": timeframe == "M1",
        "production_storage_written": False,
        "investigation": investigation_notes(),
        "error": None,
        "overall_result": "FAILED",
    }

    if args.acquire or args.force_acquire:
        if symbol != "EURUSD" or timeframe != "M1":
            report["error"] = "--acquire currently supports EURUSD M1 Kaggle sample only"
            _finalize(report)
            return 1
        try:
            path = download_kaggle_orkadd_eurusd_m1_sample(
                data_dir, force=bool(args.force_acquire)
            )
            report["source"] = "kaggle_orkadd_eurusd_1m_sample"
            report["acquired_path"] = str(path)
        except Exception as exc:  # noqa: BLE001
            report["error"] = f"acquire_failed: {type(exc).__name__}: {exc}"
            _finalize(report)
            return 1

    files = locate_data_files(data_dir, symbol)
    if not files:
        report["error"] = (
            f"No CSV in {data_dir}. Re-run with --acquire for the free Kaggle "
            "EURUSD M1 sample, or place a supported CSV manually."
        )
        _finalize(report)
        return 1

    source_path = files[0]
    report["file_name"] = source_path.name
    report["file_size_bytes"] = source_path.stat().st_size
    if report["source"] is None:
        report["source"] = "local_free_ohlc_csv"

    try:
        fmt, bars = load_free_ohlc_csv(source_path, start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"parse_failed: {type(exc).__name__}: {exc}"
        _finalize(report)
        return 1

    report["source_format"] = fmt
    report["bar_count"] = len(bars)
    if not bars:
        report["error"] = "zero bars in requested date range"
        _finalize(report)
        return 1

    report["first_timestamp"] = bars[0].timestamp.isoformat(sep=" ")
    report["last_timestamp"] = bars[-1].timestamp.isoformat(sep=" ")
    report["timezone_policy"] = bars[0].source_timezone_policy.value
    # Explicit UTC normalization already applied for Z / epoch-ms policies.
    report["timezone_conversion_applied"] = bars[0].source_timezone_policy in {
        TimezonePolicy.CONFIRMED_UTC,
        TimezonePolicy.ASSUMED_UTC_EPOCH_MS,
    }

    dropped = 0
    if args.skip_invalid_ohlc:
        kept: list[FreeOhlcBar] = []
        for bar in bars:
            if ohlc_valid(bar.open, bar.high, bar.low, bar.close):
                kept.append(bar)
            else:
                dropped += 1
        bars = kept
        report["dropped_invalid_ohlc_count"] = dropped
        report["bar_count"] = len(bars)
        if not bars:
            report["error"] = "all bars dropped as invalid OHLC"
            _finalize(report)
            return 1
        report["first_timestamp"] = bars[0].timestamp.isoformat(sep=" ")
        report["last_timestamp"] = bars[-1].timestamp.isoformat(sep=" ")
    else:
        report["dropped_invalid_ohlc_count"] = 0

    stats = analyze_bars(bars)
    report.update(stats)
    canon = try_canonical(symbol, bars)
    report.update(canon)

    report["m1_to_htf_derivation_possible"] = timeframe == "M1" and canon[
        "canonical_bar_compatible"
    ]
    report["htf_note"] = (
        "Prefer deriving M5/M15/M30/H1/H4/D1 from normalized M1 once validated."
        if timeframe == "M1"
        else f"Source timeframe is {timeframe}; do not pretend it is M1."
    )

    ok = (
        len(bars) > 0
        and stats["invalid_ohlc_count"] == 0
        and stats["out_of_order_count"] == 0
        and canon["canonical_bar_compatible"] is True
        and bars[0].source_timezone_policy != TimezonePolicy.NEEDS_CONFIRMATION
    )
    report["overall_result"] = "SUCCESS" if ok else "FAILED"
    if not ok and report["error"] is None:
        report["error"] = "validation checks failed"
    if ok and dropped:
        report["warning"] = (
            f"Skipped {dropped} invalid OHLC rows (--skip-invalid-ohlc); "
            "source quality issue, not repaired."
        )
    _finalize(report)
    return 0 if ok else 1


def _finalize(report: dict[str, object]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("=== REX FREE OHLC PROBE ===")
    print(f"source: {report.get('source')}")
    print(f"symbol: {report.get('symbol')}")
    print(f"timeframe: {report.get('timeframe')}")
    print(f"requested: {report.get('requested_start')} .. {report.get('requested_end')}")
    print(f"file: {report.get('file_name')}")
    print(f"bar_count: {report.get('bar_count')}")
    print(f"first_timestamp: {report.get('first_timestamp')}")
    print(f"last_timestamp: {report.get('last_timestamp')}")
    print(f"timezone_policy: {report.get('timezone_policy')}")
    print(f"invalid_ohlc_count: {report.get('invalid_ohlc_count')}")
    print(f"duplicate_timestamp_count: {report.get('duplicate_timestamp_count')}")
    print(f"out_of_order_count: {report.get('out_of_order_count')}")
    print(f"canonical_bar_compatible: {report.get('canonical_bar_compatible')}")
    print(f"m1_to_htf_derivation_possible: {report.get('m1_to_htf_derivation_possible')}")
    print(f"overall_result: {report.get('overall_result')}")
    if report.get("error"):
        print(f"error: {report.get('error')}")
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    raise SystemExit(main())
