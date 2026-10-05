"""Causal ATR helper for automatic zone clustering (no indicator-engine dependency)."""

from __future__ import annotations

from collections.abc import Sequence

from models.bar import Bar


def causal_atr(
    bars: Sequence[Bar],
    *,
    asof_index: int,
    period: int,
) -> float | None:
    """Average True Range on ``bars[0 : asof_index + 1]`` (inclusive).

    Returns ``None`` when the prefix is too short — callers must fall back
    explicitly rather than inventing a value.
    """
    if period < 1:
        raise ValueError("atr period must be >= 1")
    if asof_index < 0 or asof_index >= len(bars):
        return None
    prefix = bars[: asof_index + 1]
    if len(prefix) < period + 1:
        return None

    true_ranges: list[float] = []
    for index in range(1, len(prefix)):
        bar = prefix[index]
        prev_close = prefix[index - 1].close
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )
        true_ranges.append(tr)

    window = true_ranges[-period:]
    if len(window) < period:
        return None
    return sum(window) / float(period)
