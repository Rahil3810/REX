"""Deterministic M1 → higher-timeframe resampling (research-only).

Resampler version: ``free_ohlc_resample_v1``

Completeness (default)
----------------------
``fx_open_minutes_v1``:

- Buckets are aligned in **naive UTC** wall time.
- A bucket is emitted only when **every FX-open minute** in
  ``[bucket_start, bucket_end)`` has exactly one M1 bar.
- FX weekly closure heuristic (UTC, no DST):
  market is **closed** from Friday 22:00 inclusive through Sunday 22:00 exclusive.
- Fully-closed buckets (zero expected open minutes) are skipped.
- Weekend closure therefore does **not** invalidate Monday candles: Saturday /
  Sunday closed minutes are simply not required.

Partial bars are never emitted unless ``allow_partial=True`` (explicit opt-in),
in which case any non-empty contiguous-intrabucket set is aggregated (still no
lookahead beyond the source series).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from historical.bar_contract import build_canonical_bar, validate_bar_sequence
from models.bar import Bar

RESAMPLER_VERSION = "free_ohlc_resample_v1"
COMPLETENESS_RULE = "fx_open_minutes_v1"

SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")

_TF_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


@dataclass(frozen=True)
class ResampleStats:
    source_bar_count: int
    target_timeframe: str
    emitted_bar_count: int
    skipped_incomplete_buckets: int
    skipped_closed_buckets: int
    completeness_rule: str
    allow_partial: bool
    volume_type: str
    first_timestamp: datetime | None
    last_timestamp: datetime | None


@dataclass(frozen=True)
class ResampleResult:
    bars: tuple[Bar, ...]
    stats: ResampleStats
    provenance: dict[str, object] = field(default_factory=dict)


class ResampleError(ValueError):
    """Invalid resampling input."""


def timeframe_minutes(timeframe: str) -> int:
    tf = timeframe.strip().upper()
    if tf not in _TF_MINUTES:
        raise ResampleError(f"unsupported timeframe: {timeframe!r}")
    return _TF_MINUTES[tf]


def bucket_start_utc(ts: datetime, timeframe: str) -> datetime:
    """Floor ``ts`` (naive UTC) to the deterministic HTF bucket start."""
    if ts.tzinfo is not None:
        raise ResampleError("resampler requires naive UTC timestamps")
    tf = timeframe.strip().upper()
    minutes = timeframe_minutes(tf)
    if tf == "D1":
        return datetime(ts.year, ts.month, ts.day)
    if tf == "H4":
        hour = (ts.hour // 4) * 4
        return datetime(ts.year, ts.month, ts.day, hour, 0, 0)
    if minutes >= 60:
        # H1
        return datetime(ts.year, ts.month, ts.day, ts.hour, 0, 0)
    floored = (ts.minute // minutes) * minutes
    return datetime(ts.year, ts.month, ts.day, ts.hour, floored, 0)


def is_fx_market_open_minute_utc(ts: datetime) -> bool:
    """Return True if ``ts`` is inside the FX open heuristic (UTC, no DST).

    Closed: Saturday all day; Friday from 22:00; Sunday before 22:00.
    """
    if ts.tzinfo is not None:
        raise ResampleError("expected naive UTC timestamp")
    wd = ts.weekday()  # Mon=0 ... Sun=6
    if wd == 5:
        return False
    if wd == 4 and ts.hour >= 22:
        return False
    if wd == 6 and ts.hour < 22:
        return False
    return True


def expected_open_minutes(
    bucket_start: datetime,
    timeframe: str,
) -> list[datetime]:
    """List every FX-open M1 timestamp required for a complete bucket."""
    span = timeframe_minutes(timeframe)
    out: list[datetime] = []
    for i in range(span):
        minute = bucket_start + timedelta(minutes=i)
        if is_fx_market_open_minute_utc(minute):
            out.append(minute)
    return out


def _aggregate(
    symbol: str,
    bucket_ts: datetime,
    members: list[Bar],
    *,
    volume_type: str,
) -> Bar:
    members = sorted(members, key=lambda b: b.timestamp)
    open_ = members[0].open
    high = max(b.high for b in members)
    low = min(b.low for b in members)
    close = members[-1].close
    volumes = [b.volume for b in members]
    if all(v is not None for v in volumes):
        vol: float | None = float(sum(float(v) for v in volumes if v is not None))
        # Semantic remains tick_volume when summing tick volumes.
        _ = volume_type
    else:
        vol = None
    return build_canonical_bar(
        symbol=symbol,
        timestamp=bucket_ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=vol,
    )


def resample_bars(
    bars: Iterable[Bar],
    *,
    target_timeframe: str,
    volume_type: str = "tick_volume",
    allow_partial: bool = False,
    completeness_rule: str = COMPLETENESS_RULE,
) -> ResampleResult:
    """Resample M1 (or already-aligned) bars into ``target_timeframe``.

    Input bars must be chronologically sorted with unique timestamps.
    """
    tf = target_timeframe.strip().upper()
    if tf not in SUPPORTED_TIMEFRAMES:
        raise ResampleError(f"unsupported timeframe: {target_timeframe!r}")
    if completeness_rule != COMPLETENESS_RULE:
        raise ResampleError(f"unsupported completeness rule: {completeness_rule!r}")

    source = list(bars)
    if not source:
        stats = ResampleStats(
            source_bar_count=0,
            target_timeframe=tf,
            emitted_bar_count=0,
            skipped_incomplete_buckets=0,
            skipped_closed_buckets=0,
            completeness_rule=completeness_rule,
            allow_partial=allow_partial,
            volume_type=volume_type,
            first_timestamp=None,
            last_timestamp=None,
        )
        return ResampleResult(bars=(), stats=stats, provenance={"resampler_version": RESAMPLER_VERSION})

    # Validate uniqueness / order
    prev: datetime | None = None
    seen: set[datetime] = set()
    for bar in source:
        if bar.timestamp in seen:
            raise ResampleError(f"duplicate source timestamp: {bar.timestamp}")
        seen.add(bar.timestamp)
        if prev is not None and bar.timestamp < prev:
            raise ResampleError("source bars are out of order")
        if bar.timestamp.tzinfo is not None:
            raise ResampleError("source timestamps must be naive UTC")
        prev = bar.timestamp

    if tf == "M1":
        out = tuple(source)
        stats = ResampleStats(
            source_bar_count=len(source),
            target_timeframe=tf,
            emitted_bar_count=len(out),
            skipped_incomplete_buckets=0,
            skipped_closed_buckets=0,
            completeness_rule=completeness_rule,
            allow_partial=allow_partial,
            volume_type=volume_type,
            first_timestamp=out[0].timestamp,
            last_timestamp=out[-1].timestamp,
        )
        return ResampleResult(
            bars=out,
            stats=stats,
            provenance={
                "resampler_version": RESAMPLER_VERSION,
                "target_timeframe": tf,
                "completeness_rule": completeness_rule,
                "allow_partial": allow_partial,
                "volume_type": volume_type,
                "volume_note": (
                    "Bar.volume remains tick_volume when summed; never exchange volume."
                ),
            },
        )

    symbol = source[0].symbol
    buckets: dict[datetime, list[Bar]] = {}
    for bar in source:
        key = bucket_start_utc(bar.timestamp, tf)
        buckets.setdefault(key, []).append(bar)

    emitted: list[Bar] = []
    skipped_incomplete = 0
    skipped_closed = 0

    for key in sorted(buckets):
        members = buckets[key]
        expected = expected_open_minutes(key, tf)
        if not expected:
            skipped_closed += 1
            continue
        by_ts = {b.timestamp: b for b in members}
        if allow_partial:
            if not members:
                skipped_incomplete += 1
                continue
            # Still refuse internal holes among present open minutes between
            # first and last present expected minute.
            present_expected = [t for t in expected if t in by_ts]
            if not present_expected:
                skipped_incomplete += 1
                continue
            first_i = expected.index(present_expected[0])
            last_i = expected.index(present_expected[-1])
            span = expected[first_i : last_i + 1]
            if any(t not in by_ts for t in span):
                skipped_incomplete += 1
                continue
            chosen = [by_ts[t] for t in span]
            emitted.append(
                _aggregate(symbol, key, chosen, volume_type=volume_type)
            )
            continue

        # Default: require every FX-open minute in the bucket.
        if any(t not in by_ts for t in expected):
            skipped_incomplete += 1
            continue
        # Reject unexpected extra minutes inside the bucket open set (duplicates
        # already forbidden globally).
        chosen = [by_ts[t] for t in expected]
        emitted.append(_aggregate(symbol, key, chosen, volume_type=volume_type))

    emitted = validate_bar_sequence(emitted)
    stats = ResampleStats(
        source_bar_count=len(source),
        target_timeframe=tf,
        emitted_bar_count=len(emitted),
        skipped_incomplete_buckets=skipped_incomplete,
        skipped_closed_buckets=skipped_closed,
        completeness_rule=completeness_rule,
        allow_partial=allow_partial,
        volume_type=volume_type,
        first_timestamp=emitted[0].timestamp if emitted else None,
        last_timestamp=emitted[-1].timestamp if emitted else None,
    )
    provenance = {
        "resampler_version": RESAMPLER_VERSION,
        "target_timeframe": tf,
        "completeness_rule": completeness_rule,
        "allow_partial": allow_partial,
        "fx_closure": "Fri 22:00 UTC inclusive → Sun 22:00 UTC exclusive",
        "volume_type": volume_type,
        "volume_note": (
            "When all contributing M1 bars have volume, volumes are summed and "
            "still labeled tick_volume. Otherwise volume is None."
        ),
        "aggregation": {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum_or_none",
        },
    }
    return ResampleResult(bars=tuple(emitted), stats=stats, provenance=provenance)
