"""Research-only adapter: free OHLC CSV → canonical REX ``Bar`` objects.

Does not write to production ``data/historical/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from historical.bar_contract import build_canonical_bar, validate_bar_sequence
from historical.exceptions import HistoricalParseError
from models.bar import Bar
from research.free_ohlc.formats import (
    FreeOhlcBar,
    TimezonePolicy,
    VolumeSemantics,
    detect_format,
    in_date_range,
    normalize_symbol,
    parse_line,
)


ADAPTER_VERSION = "free_ohlc_adapter_v1"


@dataclass(frozen=True)
class AdapterStats:
    rows_read: int
    rows_accepted: int
    rows_dropped_invalid: int
    rows_dropped_date_filter: int
    parse_error_count: int
    invalid_ohlc_count: int
    duplicate_timestamp_count: int
    out_of_order_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    bar_count: int
    volume_type: str
    timezone_policy: str
    source_format: str
    skip_invalid_ohlc: bool


@dataclass(frozen=True)
class AdapterResult:
    bars: tuple[Bar, ...]
    stats: AdapterStats
    provenance: dict[str, object] = field(default_factory=dict)


class FreeOhlcAdapterError(ValueError):
    """Raised when free-OHLC adaptation fails under the active policy."""


def _count_duplicates_and_order(timestamps: list[datetime]) -> tuple[int, int]:
    duplicates = 0
    out_of_order = 0
    seen: set[datetime] = set()
    prev: datetime | None = None
    for ts in timestamps:
        if ts in seen:
            duplicates += 1
        seen.add(ts)
        if prev is not None and ts < prev:
            out_of_order += 1
        prev = ts
    return duplicates, out_of_order


def load_free_ohlc(
    path: Path | str,
    *,
    symbol: str,
    timeframe: str = "M1",
    start: date | None = None,
    end: date | None = None,
    skip_invalid_ohlc: bool = False,
    fmt: str | None = None,
) -> AdapterResult:
    """Load a free OHLC CSV into validated canonical ``Bar``s.

    Timestamps are normalized only according to the detected source policy
    (CONFIRMED_UTC / ASSUMED_UTC_EPOCH_MS). Naive ambiguous timestamps are refused
    by the parsers — never silently reinterpreted.
    """
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FreeOhlcAdapterError(f"CSV not found: {csv_path}")

    sym = normalize_symbol(symbol)
    tf = timeframe.strip().upper()
    raw_lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    detected = fmt or detect_format(raw_lines[:20])

    rows_read = 0
    parse_errors = 0
    dropped_date = 0
    dropped_invalid = 0
    invalid_count = 0
    accepted_rows: list[FreeOhlcBar] = []
    volume_type = VolumeSemantics.NONE.value
    tz_policy = TimezonePolicy.NEEDS_CONFIRMATION.value

    for line in raw_lines:
        try:
            row = parse_line(line, detected)
        except Exception:
            # Count only non-empty non-comment lines as parse errors.
            text = line.strip()
            if text and not text.startswith("#") and "," in text:
                parse_errors += 1
            continue
        if row is None:
            continue
        rows_read += 1
        volume_type = row.volume_semantics.value
        tz_policy = row.source_timezone_policy.value
        if not in_date_range(row.timestamp, start, end):
            dropped_date += 1
            continue

        # Canonical validation (rejects impossible OHLC; never repairs).
        try:
            build_canonical_bar(
                symbol=sym,
                timestamp=row.timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
        except HistoricalParseError:
            invalid_count += 1
            if skip_invalid_ohlc:
                dropped_invalid += 1
                continue
            raise FreeOhlcAdapterError(
                f"invalid OHLC at {row.timestamp.isoformat(sep=' ')} "
                f"(skip_invalid_ohlc=False)"
            )

        accepted_rows.append(row)

    timestamps = [r.timestamp for r in accepted_rows]
    duplicates, out_of_order = _count_duplicates_and_order(timestamps)
    if duplicates:
        raise FreeOhlcAdapterError(
            f"duplicate timestamps detected: {duplicates} "
            "(free-OHLC adapter requires unique source timestamps)"
        )
    if out_of_order:
        raise FreeOhlcAdapterError(
            f"out-of-order timestamps detected: {out_of_order}"
        )

    bars: list[Bar] = []
    for row in accepted_rows:
        bars.append(
            build_canonical_bar(
                symbol=sym,
                timestamp=row.timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
        )
    bars = validate_bar_sequence(bars)

    stats = AdapterStats(
        rows_read=rows_read,
        rows_accepted=len(bars),
        rows_dropped_invalid=dropped_invalid,
        rows_dropped_date_filter=dropped_date,
        parse_error_count=parse_errors,
        invalid_ohlc_count=invalid_count,
        duplicate_timestamp_count=duplicates,
        out_of_order_count=out_of_order,
        first_timestamp=bars[0].timestamp if bars else None,
        last_timestamp=bars[-1].timestamp if bars else None,
        bar_count=len(bars),
        volume_type=volume_type,
        timezone_policy=tz_policy,
        source_format=detected,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )
    provenance = {
        "adapter_version": ADAPTER_VERSION,
        "source": "free_ohlc_csv",
        "source_path": str(csv_path),
        "symbol": sym,
        "source_timeframe": tf,
        "timestamp_policy": tz_policy,
        "volume_type": volume_type,
        "invalid_row_policy": (
            "skip_invalid_ohlc" if skip_invalid_ohlc else "reject_invalid_ohlc"
        ),
        "requested_start": start.isoformat() if start else None,
        "requested_end": end.isoformat() if end else None,
        "note": (
            "Tick volume is preserved on Bar.volume when present but remains "
            "tick_volume semantics — never exchange volume."
        ),
    }
    return AdapterResult(bars=tuple(bars), stats=stats, provenance=provenance)
