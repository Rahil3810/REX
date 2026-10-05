"""Canonical historical bar contract for REX ingestion.

Storage timestamps are **UTC wall times** stored as timezone-naive ``datetime``
values. This matches Dukascopy/duka exports (UTC) and FeatureRepository's
``ensure_utc`` rule (naive ⇒ UTC).

Aware inputs are converted to UTC then stored naive. Naive inputs from
provider CSVs are interpreted as UTC (documented Dukascopy semantics) — they
are never reinterpreted using the local machine timezone.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from historical.exceptions import HistoricalParseError
from models.bar import Bar


def normalize_provider_timestamp(value: datetime | str) -> datetime:
    """Normalize a provider timestamp to naive UTC for HistoricalStorage.

    - Aware datetimes → convert to UTC, drop tzinfo.
    - Naive datetimes → treated as UTC wall time (Dukascopy/duka convention).
    - Strings → ISO-8601 (``Z`` / offsets allowed) or ``YYYYMMDD HHMMSS``.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            raise HistoricalParseError("empty timestamp")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y%m%d %H%M%S")
            except ValueError as exc:
                raise HistoricalParseError(f"invalid timestamp: {text!r}") from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _finite_non_negative(value: object, name: str, *, allow_zero: bool) -> float:
    if value is None:
        raise HistoricalParseError(f"missing {name}")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise HistoricalParseError(f"invalid {name}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalParseError(f"missing {name}")
        try:
            parsed = float(text)
        except ValueError as exc:
            raise HistoricalParseError(f"invalid {name}") from exc
    else:
        parsed = float(value)
    if not math.isfinite(parsed):
        raise HistoricalParseError(f"non-finite {name}")
    if parsed < 0:
        raise HistoricalParseError(f"negative {name}")
    if parsed == 0 and not allow_zero:
        raise HistoricalParseError(f"zero {name} is not allowed")
    return parsed


def validate_ohlc(
    open_: float,
    high: float,
    low: float,
    close: float,
) -> None:
    """Reject physically impossible OHLC relationships. Never coerces to 0.0."""
    if high < low:
        raise HistoricalParseError("high below low")
    if not low <= open_ <= high:
        raise HistoricalParseError("open outside high/low range")
    if not low <= close <= high:
        raise HistoricalParseError("close outside high/low range")


def build_canonical_bar(
    *,
    symbol: str,
    timestamp: datetime | str,
    open: float | str,
    high: float | str,
    low: float | str,
    close: float | str,
    volume: float | str | None = None,
) -> Bar:
    """Build one validated canonical REX ``Bar`` from provider fields."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise HistoricalParseError("missing symbol")

    ts = normalize_provider_timestamp(timestamp)
    open_ = _finite_non_negative(open, "open", allow_zero=False)
    high_ = _finite_non_negative(high, "high", allow_zero=False)
    low_ = _finite_non_negative(low, "low", allow_zero=False)
    close_ = _finite_non_negative(close, "close", allow_zero=False)
    validate_ohlc(open_, high_, low_, close_)

    vol: float | None
    if volume is None or (isinstance(volume, str) and not volume.strip()):
        vol = None
    else:
        vol = _finite_non_negative(volume, "volume", allow_zero=True)

    return Bar(
        symbol=normalized_symbol,
        timestamp=ts,
        open=open_,
        high=high_,
        low=low_,
        close=close_,
        volume=vol,
    )


def validate_bar_sequence(bars: Sequence[Bar]) -> list[Bar]:
    """Ensure chronological order and unique timestamps; return a new list."""
    ordered: list[Bar] = []
    previous: datetime | None = None
    seen: set[datetime] = set()
    for index, bar in enumerate(bars):
        if bar.timestamp in seen:
            raise HistoricalParseError(
                f"Duplicate timestamp at index {index}: {bar.timestamp.isoformat()}"
            )
        if previous is not None and bar.timestamp <= previous:
            raise HistoricalParseError(
                f"Out-of-order timestamp at index {index}: {bar.timestamp.isoformat()}"
            )
        validate_ohlc(bar.open, bar.high, bar.low, bar.close)
        seen.add(bar.timestamp)
        previous = bar.timestamp
        ordered.append(bar)
    return ordered


@dataclass(frozen=True)
class DatasetQualityReport:
    """Factual summary of an ingested historical dataset (no fabricated completeness)."""

    instrument: str
    timeframe: str
    provider: str
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    bar_count: int
    duplicate_count: int
    invalid_bar_count: int
    timestamp_gap_count: int | None
    coverage_start: str | None
    coverage_end: str | None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "provider": self.provider,
            "first_timestamp": (
                None if self.first_timestamp is None else self.first_timestamp.isoformat()
            ),
            "last_timestamp": (
                None if self.last_timestamp is None else self.last_timestamp.isoformat()
            ),
            "bar_count": self.bar_count,
            "duplicate_count": self.duplicate_count,
            "invalid_bar_count": self.invalid_bar_count,
            "timestamp_gap_count": self.timestamp_gap_count,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "notes": list(self.notes),
        }


def assess_dataset_quality(
    bars: Sequence[Bar],
    *,
    instrument: str,
    timeframe: str,
    provider: str,
    coverage_start: object | None = None,
    coverage_end: object | None = None,
    expected_step_minutes: int | None = 1,
) -> DatasetQualityReport:
    """Assess bars already intended for storage.

    Duplicate/invalid counts reflect problems found while scanning; they do not
    invent market-session completeness. Gap count is consecutive timestamp
    deltas larger than ``expected_step_minutes`` when that step is known;
    otherwise ``None`` (unknown).
    """
    notes: list[str] = [
        "Timestamps are naive UTC wall times (Dukascopy semantics).",
        "Gap count is raw timestamp spacing, not session-aware missing bars.",
    ]
    if not bars:
        return DatasetQualityReport(
            instrument=instrument.upper(),
            timeframe=timeframe.upper(),
            provider=provider,
            first_timestamp=None,
            last_timestamp=None,
            bar_count=0,
            duplicate_count=0,
            invalid_bar_count=0,
            timestamp_gap_count=0 if expected_step_minutes is not None else None,
            coverage_start=str(coverage_start) if coverage_start is not None else None,
            coverage_end=str(coverage_end) if coverage_end is not None else None,
            notes=tuple(notes + ["empty dataset"]),
        )

    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    seen: set[datetime] = set()
    duplicates = 0
    invalid = 0
    for bar in ordered:
        if bar.timestamp in seen:
            duplicates += 1
        seen.add(bar.timestamp)
        try:
            validate_ohlc(bar.open, bar.high, bar.low, bar.close)
            for name, value in (
                ("open", bar.open),
                ("high", bar.high),
                ("low", bar.low),
                ("close", bar.close),
            ):
                if not math.isfinite(value) or value <= 0:
                    raise HistoricalParseError(name)
        except HistoricalParseError:
            invalid += 1

    gap_count: int | None
    if expected_step_minutes is None:
        gap_count = None
        notes.append("timestamp_gap_count unknown (no expected step).")
    else:
        step = expected_step_minutes * 60
        gap_count = 0
        for left, right in zip(ordered, ordered[1:], strict=False):
            delta = (right.timestamp - left.timestamp).total_seconds()
            if delta > step:
                gap_count += 1

    return DatasetQualityReport(
        instrument=instrument.upper(),
        timeframe=timeframe.upper(),
        provider=provider,
        first_timestamp=ordered[0].timestamp,
        last_timestamp=ordered[-1].timestamp,
        bar_count=len(ordered),
        duplicate_count=duplicates,
        invalid_bar_count=invalid,
        timestamp_gap_count=gap_count,
        coverage_start=str(coverage_start) if coverage_start is not None else None,
        coverage_end=str(coverage_end) if coverage_end is not None else None,
        notes=tuple(notes),
    )


def rows_from_mapping(rows: Iterable[Mapping[str, object]], symbol: str) -> list[Bar]:
    """Convert provider row mappings into a validated ordered bar list."""
    bars: list[Bar] = []
    for index, row in enumerate(rows, start=1):
        try:
            timestamp = row.get("timestamp", row.get("time"))
            if timestamp is None:
                raise HistoricalParseError("missing timestamp")
            bars.append(
                build_canonical_bar(
                    symbol=symbol,
                    timestamp=timestamp if isinstance(timestamp, (datetime, str)) else str(timestamp),
                    open=row["open"],  # type: ignore[arg-type]
                    high=row["high"],  # type: ignore[arg-type]
                    low=row["low"],  # type: ignore[arg-type]
                    close=row["close"],  # type: ignore[arg-type]
                    volume=row.get("volume"),  # type: ignore[arg-type]
                )
            )
        except (KeyError, TypeError, HistoricalParseError) as exc:
            raise HistoricalParseError(f"Invalid historical row {index}: {exc}") from exc
    return validate_bar_sequence(bars)
