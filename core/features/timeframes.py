"""Causal timeframe utilities for FeatureRepository materialization.

Temporal contract
-----------------
For evaluation time ``T`` (``asof``), a feature may use ONLY observations whose
information was available at or before ``T``.

Bar timestamps are treated as interval **open** times in UTC.

For timeframe ``TF`` with duration ``D``:

    interval_start = floor_to_timeframe(timestamp, TF)
    interval_end = interval_start + D
    completion_time = interval_end

A completed HTF bar is available only when ``completion_time <= T``.

Source bars used for aggregation are restricted to ``timestamp <= T``.

Incomplete HTF intervals are never emitted as completed bars.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from models.bar import Bar

# Supported research timeframes → duration in minutes.
_TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


class UnknownTimeframeError(ValueError):
    """Raised when a timeframe string is not supported for causal aggregation."""


def ensure_utc(value: datetime) -> datetime:
    """Normalize to timezone-aware UTC. Naive datetimes are interpreted as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timeframe_minutes(timeframe: str) -> int:
    """Return duration in minutes for a known timeframe label."""
    key = timeframe.strip().upper()
    try:
        return _TIMEFRAME_MINUTES[key]
    except KeyError as exc:
        raise UnknownTimeframeError(
            f"Unsupported timeframe for causal aggregation: {timeframe!r}"
        ) from exc


def timeframe_duration(timeframe: str) -> timedelta:
    return timedelta(minutes=timeframe_minutes(timeframe))


def floor_to_timeframe(timestamp: datetime, timeframe: str) -> datetime:
    """Floor a UTC timestamp to the open of its ``timeframe`` interval."""
    ts = ensure_utc(timestamp)
    minutes = timeframe_minutes(timeframe)
    epoch_seconds = int(ts.timestamp())
    step = minutes * 60
    floored = (epoch_seconds // step) * step
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def interval_bounds(
    timestamp: datetime, timeframe: str
) -> tuple[datetime, datetime, datetime]:
    """
    Return ``(interval_start, interval_end, completion_time)`` for a bar open.

    For H1 with open 10:00:

        interval_start = 10:00
        interval_end = 11:00
        completion_time = 11:00
    """
    start = floor_to_timeframe(timestamp, timeframe)
    end = start + timeframe_duration(timeframe)
    return start, end, end


def bar_completion_time(bar: Bar, timeframe: str) -> datetime:
    """Completion instant of ``bar`` when interpreted as a ``timeframe`` candle."""
    _, _, completion = interval_bounds(bar.timestamp, timeframe)
    return completion


def normalize_bar_timestamp(bar: Bar) -> Bar:
    """Return a copy of ``bar`` with a UTC-aware timestamp."""
    ts = ensure_utc(bar.timestamp)
    if ts is bar.timestamp:
        return bar
    return Bar(
        symbol=bar.symbol,
        timestamp=ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def filter_bars_available_at(
    bars: Sequence[Bar], asof: datetime
) -> tuple[Bar, ...]:
    """Keep bars whose open timestamp is at or before ``asof`` (UTC)."""
    cutoff = ensure_utc(asof)
    return tuple(
        bar for bar in bars if ensure_utc(bar.timestamp) <= cutoff
    )


def filter_completed_bars(
    bars: Sequence[Bar], timeframe: str, asof: datetime
) -> tuple[Bar, ...]:
    """Keep bars whose ``completion_time <= asof`` for the given timeframe."""
    cutoff = ensure_utc(asof)
    return tuple(
        bar
        for bar in bars
        if bar_completion_time(bar, timeframe) <= cutoff
    )


def can_aggregate(source_timeframe: str, target_timeframe: str) -> bool:
    """True when ``target`` duration is an integer multiple of ``source``."""
    source = timeframe_minutes(source_timeframe)
    target = timeframe_minutes(target_timeframe)
    return source < target and target % source == 0


def select_aggregation_source(
    available_timeframes: Sequence[str], target_timeframe: str
) -> str | None:
    """
    Choose the finest available source TF that can aggregate into ``target``.

    Prefers the smallest duration (e.g. M1 over M15 for H1).
    """
    candidates: list[tuple[int, str]] = []
    for timeframe in available_timeframes:
        if timeframe == target_timeframe:
            continue
        try:
            if can_aggregate(timeframe, target_timeframe):
                candidates.append((timeframe_minutes(timeframe), timeframe))
        except UnknownTimeframeError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def aggregate_completed_bars(
    source_bars: Sequence[Bar],
    *,
    source_timeframe: str,
    target_timeframe: str,
    asof: datetime,
    symbol: str,
) -> tuple[Bar, ...]:
    """
    Aggregate ``source_bars`` into completed ``target_timeframe`` bars as of ``asof``.

    - Uses only source bars with ``timestamp <= asof``.
    - Emits a target bar only when ``completion_time <= asof``.
    - Requires full source coverage of the interval (no invented gaps).
    - Does not emit the incomplete current interval.
    """
    if not can_aggregate(source_timeframe, target_timeframe):
        raise ValueError(
            f"Cannot aggregate {source_timeframe} → {target_timeframe}"
        )

    asof_utc = ensure_utc(asof)
    source_delta = timeframe_duration(source_timeframe)
    target_delta = timeframe_duration(target_timeframe)
    expected_count = timeframe_minutes(target_timeframe) // timeframe_minutes(
        source_timeframe
    )

    available = filter_bars_available_at(source_bars, asof_utc)
    buckets: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in available:
        start, _, _ = interval_bounds(bar.timestamp, target_timeframe)
        buckets[start].append(bar)

    completed: list[Bar] = []
    for interval_start in sorted(buckets):
        completion = interval_start + target_delta
        if completion > asof_utc:
            continue

        group = sorted(buckets[interval_start], key=lambda item: item.timestamp)
        expected_opens = [
            interval_start + (index * source_delta)
            for index in range(expected_count)
        ]
        actual_opens = [ensure_utc(bar.timestamp) for bar in group]
        if actual_opens != expected_opens:
            # Missing/extra/misaligned source bars — do not invent an HTF bar.
            continue

        volumes = [bar.volume for bar in group]
        volume: float | None
        if any(value is None for value in volumes):
            volume = None
        else:
            volume = float(sum(volumes))  # type: ignore[arg-type]

        completed.append(
            Bar(
                symbol=symbol,
                timestamp=interval_start,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=volume,
            )
        )
    return tuple(completed)


def prepare_causal_bars(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    *,
    entry_timeframe: str,
    asof: datetime,
    higher_timeframes: Sequence[str],
    symbol: str,
) -> dict[str, tuple[Bar, ...]]:
    """
    Apply the causal contract and construct completed HTF bars where possible.

    Steps:
      1. UTC-normalize timestamps.
      2. Filter every series to ``timestamp <= asof``.
      3. For each required/requested HTF, rebuild from the finest aggregatable
         source when available (enforced causality).
      4. For remaining caller-supplied HTF without a source, keep only bars
         with ``completion_time <= asof`` (incomplete bars are dropped).
    """
    asof_utc = ensure_utc(asof)

    # 1–2. Normalize + asof filter on all provided series.
    filtered: dict[str, tuple[Bar, ...]] = {}
    for timeframe, bars in bars_by_timeframe.items():
        normalized = tuple(normalize_bar_timestamp(bar) for bar in bars)
        filtered[timeframe] = filter_bars_available_at(normalized, asof_utc)

    # Targets: configured HTFs + any higher-TF keys already present.
    targets: set[str] = set(higher_timeframes)
    try:
        entry_mins = timeframe_minutes(entry_timeframe)
    except UnknownTimeframeError:
        entry_mins = None

    for timeframe in list(filtered):
        if entry_mins is None:
            break
        try:
            if timeframe_minutes(timeframe) > entry_mins:
                targets.add(timeframe)
        except UnknownTimeframeError:
            continue

    # Also allow constructing the entry timeframe itself from a finer source
    # when the caller omitted it but supplied LTF + explicit asof.
    if entry_timeframe not in filtered or not filtered[entry_timeframe]:
        targets.add(entry_timeframe)

    result = dict(filtered)

    for target in sorted(targets, key=timeframe_minutes):
        source = select_aggregation_source(tuple(result.keys()), target)
        if source is None:
            # No LTF source — fail closed on incomplete caller bars.
            if target in result:
                completed = filter_completed_bars(
                    result[target], target, asof_utc
                )
                if completed:
                    result[target] = completed
                else:
                    result.pop(target, None)
            continue

        built = aggregate_completed_bars(
            result[source],
            source_timeframe=source,
            target_timeframe=target,
            asof=asof_utc,
            symbol=symbol,
        )
        if built:
            result[target] = built
        else:
            # No completed HTF bar yet — omit rather than invent or keep stale.
            result.pop(target, None)

    # Ensure every remaining series is completion-safe for its own label when
    # it is higher than entry (defense in depth for non-rebuilt keys).
    if entry_mins is not None:
        for timeframe, bars in list(result.items()):
            try:
                if timeframe_minutes(timeframe) > entry_mins:
                    completed = filter_completed_bars(bars, timeframe, asof_utc)
                    if completed:
                        result[timeframe] = completed
                    else:
                        result.pop(timeframe, None)
            except UnknownTimeframeError:
                continue

    return result
