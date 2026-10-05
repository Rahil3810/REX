"""Real Dukascopy historical smoke test (no production code changes).

Defaults are intentionally small (EURUSD M15, 3 calendar days) so the
downloader can be validated without a full-month/year pull.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from historical.bar_contract import assess_dataset_quality
from historical.config import load_historical_config
from historical.downloader import HistoricalDownloader
from historical.parser import HistoricalDataParser
from historical.provider import HistoricalDataProvider
from historical.storage import HistoricalStorage


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Real Dukascopy smoke test via REX HistoricalDownloader."
    )
    parser.add_argument("--symbol", default="EURUSD", help="Instrument symbol (default: EURUSD)")
    parser.add_argument(
        "--timeframe",
        default="M15",
        help="Candle timeframe token passed to duka (default: M15)",
    )
    parser.add_argument(
        "--start",
        default="2024-01-01",
        help="Inclusive start date YYYY-MM-DD (default: 2024-01-01)",
    )
    parser.add_argument(
        "--end",
        default="2024-01-03",
        help="Inclusive end date YYYY-MM-DD (default: 2024-01-03)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="duka day-worker threads (default: 1; keep low to avoid rate limits)",
    )
    return parser.parse_args()


def _parse_iso_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid {flag}={value!r}; expected YYYY-MM-DD") from exc


def main() -> int:
    args = _parse_args()
    requested_start = _parse_iso_date(args.start, "--start")
    requested_end = _parse_iso_date(args.end, "--end")
    if requested_end < requested_start:
        raise SystemExit("--end must be on or after --start")

    timeframe = str(args.timeframe).strip().upper()
    symbol = str(args.symbol).strip().upper()
    step_minutes = {"M1": 1, "M15": 15, "M30": 30}.get(timeframe)

    # load_historical_config() hard-requires M1; override after load (same pattern
    # as existing unit tests) so we do not change production validation.
    config = replace(
        load_historical_config(),
        symbols=(symbol,),
        timeframe=timeframe,
        start_date=requested_start,
        end_date=requested_end,
        data_directory=Path("data/historical"),
        overwrite_existing_files=True,
        retries=0,  # fail fast: single attempt only
        retry_delay_seconds=0,
        timeout_seconds=900,
        duka_threads=max(1, int(args.threads)),
        include_header=True,
    )

    report: dict[object, object] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "download_success": False,
        "output_paths": [],
        "bar_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "quality_result": None,
        "gaps_anomalies": None,
        "pipeline_parse_success": False,
        "pipeline_storage_success": False,
        "coverage_result": None,
        "provider_get_bars_count": None,
        "meta": None,
        "file_size_bytes": None,
        "duration_seconds": None,
        "error": None,
        "support_notes": {
            "config_loader_allows_m15": False,
            "downloader_passes_timeframe_to_duka": True,
            "duka_accepts_M15_token": True,
            "rex_resamples_from_m1": False,
            "override_method": "dataclasses.replace after load_historical_config",
            "duka_endpoint_note": (
                "Local .venv duka fetch URL host patched to datafeed.dukascopy.com"
            ),
        },
        "overall_result": "FAILED",
    }

    print("=== REX DUKASCOPY SMOKE TEST ===")
    print(f"symbol: {symbol}")
    print(f"timeframe: {timeframe}")
    print(f"requested_start: {requested_start}")
    print(f"requested_end: {requested_end}")
    print(
        "note: config JSON validation is M1-only; using replace() override "
        "(existing test pattern) without production code changes."
    )

    started = time.perf_counter()
    paths: tuple[Path, ...] = ()
    try:
        paths = HistoricalDownloader(config).download(
            symbols=(symbol,),
            start_date=requested_start,
            end_date=requested_end,
        )
        report["download_success"] = True
        report["output_paths"] = [str(p) for p in paths]
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["duration_seconds"] = round(time.perf_counter() - started, 2)
        traceback.print_exc()
        _finalize(report)
        return 1

    report["duration_seconds"] = round(time.perf_counter() - started, 2)

    storage = HistoricalStorage(config.data_directory)
    # Year partitions follow requested_start.year (same year range as defaults).
    csv_path = storage.year_path(symbol, timeframe, requested_start.year)
    meta_path = csv_path.with_suffix(".meta.json")
    report["output_paths"] = [str(csv_path), str(meta_path)]
    report["pipeline_storage_success"] = csv_path.is_file() and meta_path.is_file()
    if csv_path.is_file():
        report["file_size_bytes"] = csv_path.stat().st_size

    if meta_path.is_file():
        report["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))

    # Parse + validate via project parser/contract
    try:
        bars = HistoricalDataParser().parse_file(csv_path, symbol)
        report["pipeline_parse_success"] = True
        report["bar_count"] = len(bars)
        if bars:
            report["first_timestamp"] = bars[0].timestamp.isoformat(sep=" ")
            report["last_timestamp"] = bars[-1].timestamp.isoformat(sep=" ")
    except Exception as exc:
        report["error"] = f"parse:{type(exc).__name__}: {exc}"
        _finalize(report)
        return 1

    # Extra OHLC contract checks (parser already enforces; re-assert for report)
    invalid = 0
    for bar in bars:
        if not (
            math.isfinite(bar.open)
            and math.isfinite(bar.high)
            and math.isfinite(bar.low)
            and math.isfinite(bar.close)
            and bar.open > 0
            and bar.high > 0
            and bar.low > 0
            and bar.close > 0
            and bar.high >= bar.low
            and bar.low <= min(bar.open, bar.close)
            and bar.high >= max(bar.open, bar.close)
        ):
            invalid += 1
    duplicates = 0
    seen: set[datetime] = set()
    for bar in bars:
        if bar.timestamp in seen:
            duplicates += 1
        seen.add(bar.timestamp)

    coverage = storage.has_coverage(symbol, timeframe, requested_start, requested_end)
    report["coverage_result"] = coverage

    quality_kwargs: dict[str, object] = {
        "bars": bars,
        "instrument": symbol,
        "timeframe": timeframe,
        "provider": "dukascopy",
        "coverage_start": requested_start,
        "coverage_end": requested_end,
    }
    if step_minutes is not None:
        quality_kwargs["expected_step_minutes"] = step_minutes
    quality = assess_dataset_quality(**quality_kwargs)
    report["quality_result"] = quality.to_dict()
    report["gaps_anomalies"] = {
        "duplicate_count": duplicates,
        "invalid_ohlc_recount": invalid,
        "quality_duplicate_count": quality.duplicate_count,
        "quality_invalid_bar_count": quality.invalid_bar_count,
        "timestamp_gap_count_raw_spacing": quality.timestamp_gap_count,
        "gap_semantics": (
            "Raw timestamp spacing only. Cannot distinguish expected weekend/"
            "market-closure gaps from unexpected data gaps with current quality model."
        ),
        "meta_bar_count": (report["meta"] or {}).get("bar_count") if report["meta"] else None,
        "meta_bar_count_matches_rows": (
            (report["meta"] or {}).get("bar_count") == len(bars)
            if report["meta"]
            else False
        ),
    }

    # HistoricalDataProvider readability
    try:
        provider = HistoricalDataProvider(config, storage=storage)
        got = provider.get_bars(symbol, timeframe, requested_start, requested_end)
        report["provider_get_bars_count"] = len(got)
    except Exception as exc:
        report["error"] = f"provider:{type(exc).__name__}: {exc}"
        _finalize(report)
        return 1

    ok = (
        report["download_success"]
        and report["pipeline_parse_success"]
        and report["pipeline_storage_success"]
        and coverage
        and invalid == 0
        and duplicates == 0
        and len(bars) > 0
    )
    report["overall_result"] = "SUCCESS" if ok else "FAILED"
    _finalize(report)
    return 0 if ok else 1


def _finalize(report: dict[object, object]) -> None:
    out = Path("/tmp/rex_duka_m15_smoke_test.json")
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"download_success: {report.get('download_success')}")
    print(f"output_paths: {report.get('output_paths')}")
    print(f"bar_count: {report.get('bar_count')}")
    print(f"first_timestamp: {report.get('first_timestamp')}")
    print(f"last_timestamp: {report.get('last_timestamp')}")
    print(f"quality_result: {report.get('quality_result')}")
    print(f"gaps/anomalies: {report.get('gaps_anomalies')}")
    print(f"pipeline_parse_success: {report.get('pipeline_parse_success')}")
    print(f"pipeline_storage_success: {report.get('pipeline_storage_success')}")
    print(f"coverage_result: {report.get('coverage_result')}")
    print(f"provider_get_bars_count: {report.get('provider_get_bars_count')}")
    print(f"duration_seconds: {report.get('duration_seconds')}")
    print(f"error: {report.get('error')}")
    print(f"overall_result: {report.get('overall_result')}")
    print(f"wrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
