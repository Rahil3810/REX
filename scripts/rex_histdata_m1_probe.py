"""Research probe: HistData Generic ASCII M1 → REX Bar compatibility.

Does NOT write into production ``data/historical/``.
Does NOT modify Dukascopy / live / zone pipelines.
"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from historical.bar_contract import build_canonical_bar
from historical.exceptions import HistoricalParseError
from models.bar import Bar

DEFAULT_DIR = Path("research/data/histdata/EURUSD/M1")
SOURCE_NAME = "histdata"
SOURCE_TIMEZONE = "EST_NO_DST"  # vendor: Eastern Standard Time WITHOUT DST
REPORT_PATH = Path("/tmp/rex_histdata_m1_probe.json")

# Forex weekend closure heuristic in *source* wall-clock (EST no DST).
# Typical FX weekly gap: Friday ~17:00 → Sunday ~17:00 EST.
WEEKEND_GAP_MIN_MINUTES = 60 * 24  # gaps >= 24h treated as expected-market-closure candidates
SUSPICIOUS_INTRADAY_GAP_MINUTES = 5  # within a trading week, gaps > 5m are suspicious


@dataclass(frozen=True)
class HistDataM1Row:
    timestamp: datetime  # naive EST-no-DST wall clock; NOT converted
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HistData EURUSD M1 research probe")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DIR,
        help=f"Directory containing ZIP/CSV (default: {DEFAULT_DIR})",
    )
    p.add_argument(
        "--symbol",
        default="EURUSD",
        help="Instrument symbol (default: EURUSD)",
    )
    p.add_argument(
        "--year-month",
        default="202401",
        help="Expected year-month token in filename (default: 202401)",
    )
    return p.parse_args()


def locate_source_file(data_dir: Path, year_month: str) -> Path | None:
    if not data_dir.is_dir():
        return None
    preferred = [
        f"HISTDATA_COM_ASCII_EURUSD_M1_{year_month}.zip",
        f"DAT_ASCII_EURUSD_M1_{year_month}.csv",
        f"HISTDATA_COM_ASCII_EURUSD_M1_{year_month}.csv",
    ]
    for name in preferred:
        path = data_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    # Fallback: any matching zip/csv for the month
    matches = sorted(
        [
            *data_dir.glob(f"*EURUSD*M1*{year_month}*.zip"),
            *data_dir.glob(f"*EURUSD*M1*{year_month}*.csv"),
            *data_dir.glob(f"*EURUSD*{year_month}*.zip"),
            *data_dir.glob(f"*EURUSD*{year_month}*.csv"),
        ]
    )
    for path in matches:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _open_text_lines(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"ZIP contains no CSV: {path}")
            # Prefer DAT_ASCII_* names
            members.sort(key=lambda n: (0 if "DAT_ASCII" in n.upper() else 1, n))
            with zf.open(members[0]) as raw:
                for line in raw:
                    yield line.decode("utf-8", errors="replace")
    else:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            yield from fh


def parse_histdata_m1_line(line: str) -> HistDataM1Row | None:
    text = line.strip()
    if not text or text.lower().startswith("datetime"):
        return None
    parts = text.split(";")
    if len(parts) != 6:
        raise ValueError(f"expected 6 semicolon fields, got {len(parts)}: {text[:80]!r}")
    ts_raw, o, h, l, c, v = parts
    ts = datetime.strptime(ts_raw.strip(), "%Y%m%d %H%M%S")
    return HistDataM1Row(
        timestamp=ts,
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        volume=float(v),
    )


def validate_ohlc_row(row: HistDataM1Row) -> bool:
    vals = (row.open, row.high, row.low, row.close)
    if not all(math.isfinite(x) for x in vals):
        return False
    if not all(x > 0 for x in vals):
        return False
    if row.high < row.low:
        return False
    if not (row.low <= row.open <= row.high):
        return False
    if not (row.low <= row.close <= row.high):
        return False
    return True


def analyze_gaps(timestamps: list[datetime]) -> dict[str, object]:
    raw_gaps: list[dict[str, object]] = []
    suspicious: list[dict[str, object]] = []
    expected_closure: list[dict[str, object]] = []
    for prev, cur in zip(timestamps, timestamps[1:]):
        delta_min = (cur - prev).total_seconds() / 60.0
        if delta_min <= 1.0001:
            continue
        item = {
            "from": prev.isoformat(sep=" "),
            "to": cur.isoformat(sep=" "),
            "gap_minutes": round(delta_min, 3),
        }
        raw_gaps.append(item)
        # Weekend / long market-closure candidates vs short intraday holes
        if delta_min >= WEEKEND_GAP_MIN_MINUTES:
            expected_closure.append(item)
        elif delta_min > SUSPICIOUS_INTRADAY_GAP_MINUTES:
            suspicious.append(item)
    return {
        "raw_gap_count": len(raw_gaps),
        "expected_closure_candidate_count": len(expected_closure),
        "suspicious_gap_count": len(suspicious),
        "suspicious_gap_threshold_minutes": SUSPICIOUS_INTRADAY_GAP_MINUTES,
        "expected_closure_threshold_minutes": WEEKEND_GAP_MIN_MINUTES,
        "gap_semantics": (
            "Raw gaps are consecutive-row deltas > 1 minute in source EST-no-DST "
            "wall clock. Gaps >= 24h are tagged as expected-closure candidates "
            "(weekends / holidays). Gaps > 5m and < 24h are suspicious. "
            "This is heuristic only — not a trading-calendar oracle."
        ),
        "suspicious_gaps_sample": suspicious[:20],
        "expected_closure_sample": expected_closure[:10],
    }


def try_canonical_bars(symbol: str, rows: list[HistDataM1Row]) -> dict[str, object]:
    """Map HistData rows to REX Bar without timezone conversion.

    ``build_canonical_bar`` treats naive timestamps as UTC for *storage*
    semantics. For this research probe we intentionally pass the EST-no-DST
    wall clock through unchanged and record that production ingestion MUST
    add an explicit timezone normalization layer before writing HistoricalStorage.
    """
    built: list[Bar] = []
    errors = 0
    first_error: str | None = None
    for row in rows:
        try:
            # Preserve source wall clock literally (no tz attach / convert).
            bar = build_canonical_bar(
                symbol=symbol,
                timestamp=row.timestamp,  # naive EST-no-DST digits
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
            built.append(bar)
        except (HistoricalParseError, ValueError) as exc:
            errors += 1
            if first_error is None:
                first_error = str(exc)

    field_ok = {
        "timestamp": True,  # representable as datetime; semantics need TZ layer
        "open": True,
        "high": True,
        "low": True,
        "close": True,
        "volume": True,  # float|None on Bar; zeros allowed by contract
        "symbol": True,
    }
    return {
        "canonical_bar_compatible": errors == 0 and len(built) == len(rows) and len(rows) > 0,
        "canonical_build_error_count": errors,
        "canonical_build_first_error": first_error,
        "fields_preserved": field_ok,
        "timezone_warning": (
            "HistData timestamps are EST without DST. REX HistoricalStorage "
            "documents naive timestamps as UTC. Do NOT write HistData bars to "
            "production storage without an explicit normalization policy."
        ),
        "sample_bar": asdict(built[0]) if built else None,
    }


def assess_htf_derivation(row_count: int, duplicate_count: int, invalid_ohlc: int) -> dict[str, object]:
    ok_base = row_count > 0 and duplicate_count == 0 and invalid_ohlc == 0
    return {
        "can_derive_from_m1": {
            "M5": ok_base,
            "M15": ok_base,
            "M30": ok_base,
            "H1": ok_base,
            "H4": ok_base,
            "D1": ok_base,
        },
        "prefer_derive_vs_separate_downloads": (
            "Prefer deriving M5/M15/M30/H1/H4/D1 from a single M1 stream once "
            "timezone policy is fixed: one source of truth, consistent OHLC "
            "aggregation, fewer HistData interactive downloads. Separate HTF "
            "files only help if vendor aggregation differs from REX rules."
        ),
        "aggregation_notes": (
            "Standard OHLCV resample: open=first, high=max, low=min, close=last; "
            "volume=sum of source volume (often zero on HistData M1). "
            "Bucket boundaries must use the chosen normalized timeline, not mixed TZ."
        ),
    }


def tick_format_notes() -> dict[str, object]:
    return {
        "downloaded": False,
        "format": "Generic ASCII Tick",
        "example_filename_pattern": "DAT_ASCII_EURUSD_T_YYYYMM.csv",
        "fields": ["DateTime", "Bid", "Ask", "Volume"],
        "separator": ",",
        "timestamp_format": "YYYYMMDD HHMMSSNNN (millisecond)",
        "source_timezone": SOURCE_TIMEZONE,
        "volume_note": (
            "Vendor examples show Volume=0; treat as source-provided field, "
            "not exchange volume. Do not fabricate."
        ),
        "future_rex_use": [
            "tick activity density",
            "spread (ask-bid) distributions",
            "bid/ask behavior around zones",
            "liquidity proxies",
            "zone interaction quality evidence",
        ],
        "architecture_note": (
            "Future path: HistDataTickSource → optional tick store / features; "
            "M1 bars remain canonical Bar[]. Tick is additive evidence, not a "
            "replacement for the Bar contract."
        ),
    }


def manual_download_instructions(year_month: str) -> dict[str, object]:
    y, m = year_month[:4], year_month[4:]
    return {
        "required": True,
        "file": f"HISTDATA_COM_ASCII_EURUSD_M1_{year_month}.zip",
        "page": (
            "https://www.histdata.com/download-free-forex-historical-data/"
            f"?/ascii/1-minute-bar-quotes/eurusd/{y}/{int(m)}"
        ),
        "destination": str(DEFAULT_DIR),
        "reason": (
            "HistData get.php requires an interactive page token (tk) that is "
            "empty in raw HTML; safe automated download was not available without "
            "bypassing site protections."
        ),
    }


def research_assessment(report: dict[str, object]) -> dict[str, object]:
    rows = int(report.get("row_count") or 0)
    zero_vol = report.get("zero_volume_count")
    vol_always_zero = report.get("volume_always_zero")
    compatible = bool(report.get("canonical_bar_compatible"))
    has_file = bool(report.get("file_name"))

    return {
        "can_rex_reliably_ingest_histdata_m1": (
            "Conditionally yes for research parsing/OHLC integrity once the ZIP "
            "is present locally; production ingestion is blocked until an "
            "explicit EST-no-DST → UTC (or labeled-tz) normalization layer exists. "
            "Acquisition is interactive (manual ZIP), which is weaker than a "
            "stable bulk API."
            if has_file
            else "Not yet validated on real January 2024 bytes — file missing. "
            "Parser/probe is ready; complete manual download first."
        ),
        "timestamp_requires_timezone_normalization_layer": True,
        "timestamp_detail": (
            "Vendor: EST without DST. REX storage assumes naive==UTC for Dukascopy. "
            "Mixing without conversion would shift sessions/features by ~5h and "
            "break DST-period alignment. Do not silently reinterpret."
        ),
        "is_volume_useful_for_rex": (
            "Unlikely as exchange volume. HistData documents Volume as a field but "
            "examples are 0; treat as source-provided tick-activity placeholder. "
            f"Observed volume_always_zero={vol_always_zero}, zero_volume_count={zero_vol}."
        ),
        "volume_always_zero": vol_always_zero,
        "fabricate_volume": False,
        "can_derive_htf_from_m1": report.get("htf_derivation"),
        "prefer_derive_m15_m30_from_m1": True,
        "suitability": {
            "zone_generation": (
                "Yes after TZ normalization — M1→HTF OHLC is sufficient for "
                "swing/zone geometry; volume not required."
                if compatible
                else "Pending real-file validation / compatibility."
            ),
            "zone_evaluation": (
                "Yes for price-path MFE/MAE after TZ normalization; tick/spread "
                "would be optional future evidence."
                if compatible
                else "Pending real-file validation / compatibility."
            ),
            "feature_generation": (
                "Yes for price/structure features after TZ normalization; avoid "
                "volume-based features unless volume proves non-zero and meaningful."
                if compatible
                else "Pending real-file validation / compatibility."
            ),
            "backtesting": (
                "Usable for research backtests after TZ policy + HTF resample; "
                "not yet wired to production HistoricalStorage."
                if compatible
                else "Pending real-file validation / compatibility."
            ),
        },
        "rows_analyzed": rows,
    }


def main() -> int:
    args = _parse_args()
    symbol = args.symbol.strip().upper()
    data_dir: Path = args.data_dir
    year_month = args.year_month.strip()

    report: dict[str, object] = {
        "source": SOURCE_NAME,
        "symbol": symbol,
        "timeframe": "M1",
        "source_timezone": SOURCE_TIMEZONE,
        "file_name": None,
        "file_size_bytes": None,
        "row_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "duplicate_count": None,
        "invalid_ohlc_count": None,
        "out_of_order_count": None,
        "raw_gap_count": None,
        "zero_volume_count": None,
        "min_volume": None,
        "max_volume": None,
        "average_volume": None,
        "volume_always_zero": None,
        "volume_semantics": (
            "source-provided volume/tick-activity field; NOT assumed exchange volume"
        ),
        "canonical_bar_compatible": False,
        "production_storage_written": False,
        "manual_download": manual_download_instructions(year_month),
        "tick_data_future": tick_format_notes(),
        "error": None,
        "overall_result": "FAILED",
    }

    source = locate_source_file(data_dir, year_month)
    if source is None:
        report["error"] = (
            f"No HistData file found in {data_dir}. "
            f"Download {report['manual_download']['file']} manually."
        )
        report["research_assessment"] = research_assessment(report)
        _finalize(report)
        return 1

    report["file_name"] = source.name
    report["file_size_bytes"] = source.stat().st_size

    rows: list[HistDataM1Row] = []
    parse_errors = 0
    first_parse_error: str | None = None
    try:
        for line in _open_text_lines(source):
            try:
                row = parse_histdata_m1_line(line)
            except Exception as exc:  # noqa: BLE001 — research probe tallies bad rows
                parse_errors += 1
                if first_parse_error is None:
                    first_parse_error = f"{type(exc).__name__}: {exc}"
                continue
            if row is None:
                continue
            rows.append(row)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"read_failed: {type(exc).__name__}: {exc}"
        report["research_assessment"] = research_assessment(report)
        _finalize(report)
        return 1

    report["row_count"] = len(rows)
    report["parse_error_count"] = parse_errors
    report["parse_first_error"] = first_parse_error
    if not rows:
        report["error"] = "file contained zero parsable M1 rows"
        report["research_assessment"] = research_assessment(report)
        _finalize(report)
        return 1

    report["first_timestamp"] = rows[0].timestamp.isoformat(sep=" ")
    report["last_timestamp"] = rows[-1].timestamp.isoformat(sep=" ")

    invalid = 0
    for row in rows:
        if not validate_ohlc_row(row):
            invalid += 1
    report["invalid_ohlc_count"] = invalid

    duplicates = 0
    out_of_order = 0
    seen: set[datetime] = set()
    prev: datetime | None = None
    for row in rows:
        if row.timestamp in seen:
            duplicates += 1
        seen.add(row.timestamp)
        if prev is not None and row.timestamp < prev:
            out_of_order += 1
        prev = row.timestamp
    report["duplicate_count"] = duplicates
    report["out_of_order_count"] = out_of_order

    volumes = [row.volume for row in rows]
    report["min_volume"] = min(volumes)
    report["max_volume"] = max(volumes)
    report["average_volume"] = round(sum(volumes) / len(volumes), 6)
    report["zero_volume_count"] = sum(1 for v in volumes if v == 0.0)
    report["volume_always_zero"] = report["zero_volume_count"] == len(volumes)

    gap_info = analyze_gaps([r.timestamp for r in rows])
    report["raw_gap_count"] = gap_info["raw_gap_count"]
    report["gap_analysis"] = gap_info

    canon = try_canonical_bars(symbol, rows)
    report.update(canon)

    report["htf_derivation"] = assess_htf_derivation(len(rows), duplicates, invalid)
    report["research_assessment"] = research_assessment(report)

    ok = (
        len(rows) > 0
        and invalid == 0
        and duplicates == 0
        and out_of_order == 0
        and parse_errors == 0
        and report["canonical_bar_compatible"] is True
    )
    report["overall_result"] = "SUCCESS" if ok else "FAILED"
    if not ok and report["error"] is None:
        report["error"] = "validation checks failed (see counts)"
    _finalize(report)
    return 0 if ok else 1


def _finalize(report: dict[str, object]) -> None:
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("=== REX HISTDATA M1 PROBE ===")
    print(f"source: {report.get('source')}")
    print(f"symbol: {report.get('symbol')}")
    print(f"timeframe: {report.get('timeframe')}")
    print(f"file: {report.get('file_name')}")
    print(f"file_size_bytes: {report.get('file_size_bytes')}")
    print(f"rows: {report.get('row_count')}")
    print(f"first_timestamp: {report.get('first_timestamp')}")
    print(f"last_timestamp: {report.get('last_timestamp')}")
    print(f"source_timezone: {report.get('source_timezone')}")
    print(f"duplicate_count: {report.get('duplicate_count')}")
    print(f"invalid_ohlc_count: {report.get('invalid_ohlc_count')}")
    print(f"out_of_order_count: {report.get('out_of_order_count')}")
    print(f"raw_gap_count: {report.get('raw_gap_count')}")
    print(f"zero_volume_count: {report.get('zero_volume_count')}")
    print(f"min_volume: {report.get('min_volume')}")
    print(f"max_volume: {report.get('max_volume')}")
    print(f"average_volume: {report.get('average_volume')}")
    print(f"canonical_bar_compatible: {report.get('canonical_bar_compatible')}")
    print(f"overall_result: {report.get('overall_result')}")
    if report.get("error"):
        print(f"error: {report.get('error')}")
    print(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    raise SystemExit(main())
