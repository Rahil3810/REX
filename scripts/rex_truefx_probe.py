"""Research-only TrueFX historical tick probe.

Does NOT write to production ``data/historical/``.
Does NOT authenticate or bypass TrueFX access controls.
Reads local monthly ZIP/CSV placed under ``research/data/truefx/``.

Acquisition (as of investigation):
- Historical downloads: free account required (MemberPress gate).
- Public unauthenticated download: not available.
- Legacy webrates API (``https://webrates.truefx.com/rates/connect.html``):
  currently returns an empty body — not usable for historical or live snapshots.
- Catalog UI (logged-in) currently lists only recent months (e.g. 2025-11..2026-01);
  listed file URLs may 404 — treat real-byte acquisition as blocked until a local
  ZIP is obtained manually via the official download UI.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from historical.bar_contract import build_canonical_bar
from historical.exceptions import HistoricalParseError
from research.truefx.tick_csv import (
    TrueFXTick,
    in_date_range,
    iter_truefx_csv_lines,
    locate_truefx_files,
    normalize_symbol,
    parse_truefx_tick_line,
    tick_prices_valid,
)

SOURCE_NAME = "truefx"
REPORT_PATH = Path("/tmp/rex_truefx_probe.json")
DEFAULT_DATA_DIR = Path("research/data/truefx/EURUSD")

# Timezone policy: historical download page does NOT document timezone.
# Secondary sources / legacy Web API docs claim GMT. We do NOT convert.
SOURCE_TIMEZONE_LABEL = "UNCONFIRMED_GMT_CLAIMED_BY_SECONDARY_SOURCES"
TIMEZONE_POLICY_STATUS = "NEEDS_CONFIRMATION"


def _parse_args() -> argparse.Namespace:
    today = date.today()
    # Prefer a tiny window; caller must still supply a local monthly archive.
    default_end = today.replace(day=1) - timedelta(days=1)  # last day of prior month
    default_start = default_end  # single calendar day
    p = argparse.ArgumentParser(description="TrueFX historical tick research probe")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default=default_start.isoformat(), help="YYYY-MM-DD inclusive")
    p.add_argument("--end", default=default_end.isoformat(), help="YYYY-MM-DD inclusive")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument(
        "--max-ticks",
        type=int,
        default=50_000,
        help="Safety cap on ticks parsed after date filter (default 50000)",
    )
    return p.parse_args()


def _parse_iso_date(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid {flag}={value!r}; expected YYYY-MM-DD") from exc


def access_findings() -> dict[str, object]:
    return {
        "historical_download_requires_free_account": True,
        "public_unauthenticated_historical_endpoint": False,
        "legacy_webrates_snapshot_status": (
            "https://webrates.truefx.com/rates/connect.html currently returns "
            "HTTP 200 with an empty body — not usable without further vendor recovery"
        ),
        "paid_streaming_plans": {
            "Professional_USD_per_month": 4950,
            "Institutional_USD_per_month": 7450,
            "note": "Paid FIX streaming is separate from free historical downloads",
        },
        "official_historical_page": "https://www.truefx.com/truefx-historical-downloads-2/",
        "documented_format": {
            "columns": ["pair", "timestamp", "bid", "ask"],
            "header": False,
            "timestamp_example": "YYYYMMDD HH:MM:SS.mmm",
            "volume_column": False,
            "top_of_book": True,
            "source_description": "Institutional prices sourced from Integral OCX (vendor claim)",
        },
        "manual_download_instructions": [
            "Register/login free at truefx.com",
            "Open Historical Downloads",
            "Download one monthly ZIP for EURUSD (smallest available unit)",
            f"Place under {DEFAULT_DATA_DIR}/ (e.g. EURUSD-2026-01.zip)",
            "Re-run this probe with --start/--end covering a single day inside that month",
        ],
        "observed_catalog_issue": (
            "Logged-in catalog showed recent months (e.g. 2025-11, 2025-12, 2026-01) "
            "with EURUSD ZIP links that returned HTTP 404 when fetched — "
            "vendor download plumbing may be broken; local file still required."
        ),
    }


def derive_m1_candidates(
    ticks: list[TrueFXTick],
) -> dict[str, object]:
    """Research-only M1 aggregation sketches (bid / ask / mid) — not production."""
    if not ticks:
        return {
            "can_derive_m1": False,
            "m1_bar_count_bid": 0,
            "m1_bar_count_ask": 0,
            "m1_bar_count_mid": 0,
            "canonical_bar_compatible_mid": False,
            "price_basis_decision": "UNDECIDED",
        }

    def bucket(ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    groups: dict[datetime, list[TrueFXTick]] = defaultdict(list)
    for tick in ticks:
        groups[bucket(tick.timestamp)].append(tick)

    def ohlc(prices: list[float]) -> tuple[float, float, float, float]:
        return prices[0], max(prices), min(prices), prices[-1]

    bid_bars = 0
    ask_bars = 0
    mid_bars = 0
    mid_canonical_ok = 0
    mid_canonical_err = 0
    first_err: str | None = None

    for minute, bucket_ticks in sorted(groups.items()):
        bids = [t.bid for t in bucket_ticks]
        asks = [t.ask for t in bucket_ticks]
        mids = [t.midpoint for t in bucket_ticks]
        if bids:
            bid_bars += 1
        if asks:
            ask_bars += 1
        if mids:
            mid_bars += 1
            o, h, l, c = ohlc(mids)
            try:
                build_canonical_bar(
                    symbol=normalize_symbol(bucket_ticks[0].pair),
                    timestamp=minute,  # naive source minute; NOT converted
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=None,  # TrueFX ticks have no volume — do not fabricate
                )
                mid_canonical_ok += 1
            except (HistoricalParseError, ValueError) as exc:
                mid_canonical_err += 1
                if first_err is None:
                    first_err = str(exc)

    return {
        "can_derive_m1": True,
        "aggregation_rule": {
            "open": "first tick price in minute",
            "high": "max tick price in minute",
            "low": "min tick price in minute",
            "close": "last tick price in minute",
            "volume": "None (source has no volume; never fabricate)",
        },
        "m1_bar_count_bid": bid_bars,
        "m1_bar_count_ask": ask_bars,
        "m1_bar_count_mid": mid_bars,
        "canonical_bar_compatible_mid": mid_canonical_err == 0 and mid_bars > 0,
        "mid_canonical_ok": mid_canonical_ok,
        "mid_canonical_error_count": mid_canonical_err,
        "mid_canonical_first_error": first_err,
        "price_basis_decision": "UNDECIDED",
        "price_basis_note": (
            "Preserve bid, ask, midpoint, spread in research representation. "
            "Do not choose bid vs ask vs mid as REX canonical until source "
            "semantics and research goals are fixed."
        ),
        "htf_from_m1": {
            "M5": True,
            "M15": True,
            "M30": True,
            "H1": True,
            "H4": True,
            "D1": True,
            "prefer_derive_vs_separate": True,
            "requires_timezone_normalization_first": True,
        },
    }


def analyze_ticks(ticks: list[TrueFXTick]) -> dict[str, object]:
    invalid = 0
    duplicates = 0
    out_of_order = 0
    seen: set[datetime] = set()
    prev: datetime | None = None
    spreads: list[float] = []

    for tick in ticks:
        if not tick_prices_valid(tick):
            invalid += 1
        if tick.timestamp in seen:
            duplicates += 1
        seen.add(tick.timestamp)
        if prev is not None and tick.timestamp < prev:
            out_of_order += 1
        prev = tick.timestamp
        if tick_prices_valid(tick):
            spreads.append(tick.spread)

    # Gap stats on consecutive tick times (milliseconds)
    gaps_ms: list[float] = []
    for a, b in zip(ticks, ticks[1:]):
        gaps_ms.append((b.timestamp - a.timestamp).total_seconds() * 1000.0)

    gap_report: dict[str, object]
    if gaps_ms:
        gap_report = {
            "consecutive_gap_count": len(gaps_ms),
            "min_gap_ms": min(gaps_ms),
            "max_gap_ms": max(gaps_ms),
            "median_gap_ms": statistics.median(gaps_ms),
            "gaps_gt_1s": sum(1 for g in gaps_ms if g > 1000),
            "gaps_gt_60s": sum(1 for g in gaps_ms if g > 60_000),
            "gaps_gt_1h": sum(1 for g in gaps_ms if g > 3_600_000),
            "semantics": (
                "Raw consecutive-tick deltas only. Large gaps may be weekends/"
                "closures or missing data — not auto-classified as bad."
            ),
        }
    else:
        gap_report = {"consecutive_gap_count": 0}

    spread_report: dict[str, object]
    if spreads:
        spread_report = {
            "count": len(spreads),
            "min": min(spreads),
            "max": max(spreads),
            "mean": round(sum(spreads) / len(spreads), 10),
            "median": statistics.median(spreads),
            "negative_or_zero_count": sum(1 for s in spreads if s <= 0),
        }
    else:
        spread_report = {"count": 0}

    return {
        "invalid_price_count": invalid,
        "duplicate_timestamp_count": duplicates,
        "out_of_order_count": out_of_order,
        "gap_statistics": gap_report,
        "spread_statistics": spread_report,
        "volume_available": False,
        "volume_note": "TrueFX historical CSV has no volume field; do not fabricate.",
    }


def research_assessment(report: dict[str, object]) -> dict[str, object]:
    got_real = bool(report.get("tick_count"))
    return {
        "A_can_get_real_eurusd_historical_now": (
            "Yes — local file parsed successfully."
            if got_real
            else "Not yet — no local TrueFX ZIP/CSV under research/data/truefx; "
            "public endpoints do not serve historical archives; listed download "
            "URLs were observed returning 404."
        ),
        "B_free_for_research": (
            "Vendor advertises historical tick downloads at zero cost with free "
            "registration. Paid Professional/Institutional plans are for live "
            "streaming, not required for historical downloads (per site copy)."
        ),
        "C_requires_account": True,
        "D_easiest_acquisition": (
            "Free TrueFX account → Historical Downloads UI → monthly EURUSD ZIP → "
            f"place in {DEFAULT_DATA_DIR}/ → run this probe on a 1-day window."
        ),
        "E_timestamp_timezone_policy": {
            "source_timezone_label": SOURCE_TIMEZONE_LABEL,
            "status": TIMEZONE_POLICY_STATUS,
            "required_policy": (
                "Do not silently convert. Confirm with TrueFX whether historical "
                "CSV timestamps are GMT/UTC (legacy API docs claim GMT). Then "
                "normalize explicitly to REX storage UTC-naive before production."
            ),
        },
        "F_can_derive_htf": (
            "Yes in principle from tick→M1→HTF after timezone confirmation and "
            "price-basis decision (bid/ask/mid)."
            if got_real
            else "Likely yes once real ticks are obtained; not proven on real bytes yet."
        ),
        "G_eventual_HistoricalDataProvider": (
            "Plausible as a research HistoricalBarSource once account acquisition "
            "is reliable, timezone is confirmed, and bid/ask→Bar mapping is chosen. "
            "Do not implement production adapter yet."
        ),
        "H_blocker": report.get("error")
        or (
            None
            if got_real and report.get("timezone_policy_status") != "NEEDS_CONFIRMATION"
            else (
                "Primary blocker: no successfully downloaded real TrueFX bytes in "
                "research/data/truefx. Secondary: timezone for historical CSV is "
                "not confirmed on the official downloads page (secondary sources "
                "claim GMT). Tertiary: catalog download URLs observed as 404."
            )
        ),
        "vs_candidates": {
            "dukascopy": "Blocked by provider HTTP 403/429 on public datafeed path",
            "histdata": "Interactive/manual download; EST-no-DST timestamps",
            "mt5": "No broker/install path available",
            "truefx": (
                "Best theoretical tick quality (bid/ask, ms, institutional TOB) "
                "and free historical claim, but acquisition currently gated + "
                "download plumbing unreliable in this environment"
            ),
        },
    }


def main() -> int:
    args = _parse_args()
    symbol = normalize_symbol(args.symbol)
    start = _parse_iso_date(args.start, "--start")
    end = _parse_iso_date(args.end, "--end")
    if end < start:
        raise SystemExit("--end must be on or after --start")
    data_dir: Path = args.data_dir

    report: dict[str, object] = {
        "source": SOURCE_NAME,
        "symbol": symbol,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "data_dir": str(data_dir),
        "file_name": None,
        "file_size_bytes": None,
        "tick_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "timestamp_precision": "millisecond (fractional seconds in CSV)",
        "source_timezone": SOURCE_TIMEZONE_LABEL,
        "timezone_policy_status": TIMEZONE_POLICY_STATUS,
        "timezone_conversion_applied": False,
        "bid_ask_available": True,
        "volume_available": False,
        "invalid_price_count": None,
        "duplicate_timestamp_count": None,
        "out_of_order_count": None,
        "gap_statistics": None,
        "spread_statistics": None,
        "m1_derivation": None,
        "canonical_bar_compatible": False,
        "production_storage_written": False,
        "access": access_findings(),
        "error": None,
        "overall_result": "FAILED",
    }

    files = locate_truefx_files(data_dir, symbol)
    if not files:
        report["error"] = (
            f"No local TrueFX ZIP/CSV for {symbol} under {data_dir}. "
            "Historical downloads require a free TrueFX login; this probe will "
            "not authenticate or bypass gates. Place an official monthly archive "
            "locally and re-run."
        )
        report["research_assessment"] = research_assessment(report)
        # Timezone ambiguity alone would block production ingest; acquisition
        # is the immediate blocker for this probe run.
        _finalize(report)
        return 1

    # Prefer the file whose month overlaps the requested window when possible.
    source = files[0]
    for path in files:
        name = path.name.upper()
        token = f"{start.year}-{start.month:02d}"
        if token in name or f"{start.year}{start.month:02d}" in name:
            source = path
            break

    report["file_name"] = source.name
    report["file_size_bytes"] = source.stat().st_size
    report["files_found"] = [p.name for p in files]

    ticks: list[TrueFXTick] = []
    parse_errors = 0
    first_parse_error: str | None = None
    skipped_outside_range = 0

    try:
        for line in iter_truefx_csv_lines(source):
            try:
                tick = parse_truefx_tick_line(line)
            except Exception as exc:  # noqa: BLE001 — tally bad rows
                parse_errors += 1
                if first_parse_error is None:
                    first_parse_error = f"{type(exc).__name__}: {exc}"
                continue
            if tick is None:
                continue
            if normalize_symbol(tick.pair) not in {symbol, normalize_symbol(symbol)}:
                # Allow EUR/USD vs EURUSD
                if normalize_symbol(tick.pair) != symbol:
                    continue
            if not in_date_range(tick.timestamp, start, end):
                skipped_outside_range += 1
                continue
            ticks.append(tick)
            if len(ticks) >= max(1, int(args.max_ticks)):
                break
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"read_failed: {type(exc).__name__}: {exc}"
        report["research_assessment"] = research_assessment(report)
        _finalize(report)
        return 1

    report["parse_error_count"] = parse_errors
    report["parse_first_error"] = first_parse_error
    report["skipped_outside_range"] = skipped_outside_range
    report["tick_count"] = len(ticks)
    report["max_ticks_cap_hit"] = len(ticks) >= max(1, int(args.max_ticks))

    if not ticks:
        report["error"] = (
            "Local file found but zero ticks matched the requested date range / parse."
        )
        report["research_assessment"] = research_assessment(report)
        _finalize(report)
        return 1

    report["first_timestamp"] = ticks[0].timestamp.isoformat(sep=" ")
    report["last_timestamp"] = ticks[-1].timestamp.isoformat(sep=" ")

    stats = analyze_ticks(ticks)
    report.update(stats)

    m1 = derive_m1_candidates(ticks)
    report["m1_derivation"] = m1
    report["canonical_bar_compatible"] = bool(m1.get("canonical_bar_compatible_mid"))

    # Even with valid ticks, timezone confirmation is still required for production.
    ok = (
        len(ticks) > 0
        and stats["invalid_price_count"] == 0
        and stats["out_of_order_count"] == 0
        and parse_errors == 0
        and report["canonical_bar_compatible"] is True
    )
    # Mark SUCCESS for research parse quality, but keep timezone status explicit.
    report["overall_result"] = "SUCCESS" if ok else "FAILED"
    if ok and TIMEZONE_POLICY_STATUS == "NEEDS_CONFIRMATION":
        report["warning"] = (
            "Parse/validation succeeded on local bytes, but timezone remains "
            "NEEDS_CONFIRMATION — do not write to production HistoricalStorage."
        )
    report["research_assessment"] = research_assessment(report)
    _finalize(report)
    return 0 if ok else 1


def _finalize(report: dict[str, object]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("=== REX TRUEFX PROBE ===")
    print(f"source: {report.get('source')}")
    print(f"symbol: {report.get('symbol')}")
    print(f"requested_start: {report.get('requested_start')}")
    print(f"requested_end: {report.get('requested_end')}")
    print(f"file: {report.get('file_name')}")
    print(f"file_size_bytes: {report.get('file_size_bytes')}")
    print(f"tick_count: {report.get('tick_count')}")
    print(f"first_timestamp: {report.get('first_timestamp')}")
    print(f"last_timestamp: {report.get('last_timestamp')}")
    print(f"source_timezone: {report.get('source_timezone')}")
    print(f"timezone_policy_status: {report.get('timezone_policy_status')}")
    print(f"invalid_price_count: {report.get('invalid_price_count')}")
    print(f"duplicate_timestamp_count: {report.get('duplicate_timestamp_count')}")
    print(f"out_of_order_count: {report.get('out_of_order_count')}")
    print(f"canonical_bar_compatible: {report.get('canonical_bar_compatible')}")
    print(f"overall_result: {report.get('overall_result')}")
    if report.get("error"):
        print(f"error: {report.get('error')}")
    if report.get("warning"):
        print(f"warning: {report.get('warning')}")
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    raise SystemExit(main())
