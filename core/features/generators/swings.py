"""Swing detection primitive — ported from legacy TrendAnalyzer._find_swings.

Detection mathematics are unchanged: strict left/right fractal extrema.
This module additionally records swing *events* (id, kind, index, times)
so downstream structure logic can reference confirmed swings safely.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core.features.config import SwingDetectionConfig
from core.market import Instrument
from models.bar import Bar


class SwingKind(StrEnum):
    """Whether a confirmed fractal extreme is a swing high or swing low."""

    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingEvent:
    """A confirmed fractal swing with stable identity and timing.

    ``timestamp`` is the source (candidate) bar open time.
    ``confirmation_time`` is when the swing became known
    (``bars[index + right_bars].timestamp``). These are not the same instant.
    """

    id: str
    timeframe: str
    kind: SwingKind
    price: float
    index: int
    timestamp: datetime
    confirmation_index: int
    confirmation_time: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "timeframe": self.timeframe,
            "kind": self.kind.value,
            "price": self.price,
            "index": self.index,
            "timestamp": self.timestamp.isoformat(),
            "confirmation_index": self.confirmation_index,
            "confirmation_time": self.confirmation_time.isoformat(),
        }

    @staticmethod
    def from_dict(payload: Mapping[str, object]) -> SwingEvent:
        return SwingEvent(
            id=str(payload["id"]),
            timeframe=str(payload["timeframe"]),
            kind=SwingKind(str(payload["kind"])),
            price=float(payload["price"]),  # type: ignore[arg-type]
            index=int(payload["index"]),  # type: ignore[arg-type]
            timestamp=datetime.fromisoformat(str(payload["timestamp"])),
            confirmation_index=int(payload["confirmation_index"]),  # type: ignore[arg-type]
            confirmation_time=datetime.fromisoformat(
                str(payload["confirmation_time"])
            ),
        )


def make_swing_id(timeframe: str, kind: SwingKind, source_index: int) -> str:
    """Deterministic swing id unique within a timeframe series."""
    return f"{timeframe}:{kind.value}:{source_index}"


@dataclass(frozen=True)
class TimeframeSwings:
    """Confirmed swing events for one timeframe.

    Authoritative model is ``swings`` (typed events).
    ``swing_highs`` / ``swing_lows`` are compatibility projections of prices
    in chronological detection order (same order as legacy float tuples).
    """

    timeframe: str
    swings: tuple[SwingEvent, ...]

    @property
    def swing_highs(self) -> tuple[float, ...]:
        return tuple(
            event.price for event in self.swings if event.kind == SwingKind.HIGH
        )

    @property
    def swing_lows(self) -> tuple[float, ...]:
        return tuple(
            event.price for event in self.swings if event.kind == SwingKind.LOW
        )

    @property
    def highs(self) -> tuple[SwingEvent, ...]:
        return tuple(event for event in self.swings if event.kind == SwingKind.HIGH)

    @property
    def lows(self) -> tuple[SwingEvent, ...]:
        return tuple(event for event in self.swings if event.kind == SwingKind.LOW)

    @classmethod
    def from_prices(
        cls,
        timeframe: str,
        swing_highs: Sequence[float],
        swing_lows: Sequence[float],
    ) -> TimeframeSwings:
        """Build synthetic events from price tuples for trend-unit tests.

        Timestamps/indices are placeholders and must not be used for
        causality research — prefer ``SwingGenerator`` for real series.
        """
        epoch = datetime(1970, 1, 1)
        events: list[SwingEvent] = []
        for offset, price in enumerate(swing_highs):
            index = offset * 2
            events.append(
                SwingEvent(
                    id=make_swing_id(timeframe, SwingKind.HIGH, index),
                    timeframe=timeframe,
                    kind=SwingKind.HIGH,
                    price=float(price),
                    index=index,
                    timestamp=epoch,
                    confirmation_index=index,
                    confirmation_time=epoch,
                )
            )
        for offset, price in enumerate(swing_lows):
            index = offset * 2 + 1
            events.append(
                SwingEvent(
                    id=make_swing_id(timeframe, SwingKind.LOW, index),
                    timeframe=timeframe,
                    kind=SwingKind.LOW,
                    price=float(price),
                    index=index,
                    timestamp=epoch,
                    confirmation_index=index,
                    confirmation_time=epoch,
                )
            )
        return cls(timeframe=timeframe, swings=tuple(events))


@dataclass(frozen=True)
class SwingFeatures:
    """Swing extremes keyed by timeframe."""

    by_timeframe: Mapping[str, TimeframeSwings]


class SwingGenerator:
    """Strict local extrema swing detector (canonical implementation)."""

    feature_id = "swings"

    def __init__(self, config: SwingDetectionConfig) -> None:
        self._config = config

    def generate(
        self,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        instrument: Instrument,
        *,
        entry_timeframe: str,
        asof: datetime | None = None,
    ) -> SwingFeatures:
        _ = instrument, entry_timeframe
        by_timeframe: dict[str, TimeframeSwings] = {}
        for timeframe, bars in bars_by_timeframe.items():
            events = self._find_swing_events(tuple(bars), timeframe)
            if asof is not None:
                events = tuple(
                    event
                    for event in events
                    if event.confirmation_time <= asof
                )
            by_timeframe[timeframe] = TimeframeSwings(
                timeframe=timeframe,
                swings=events,
            )
        return SwingFeatures(by_timeframe=by_timeframe)

    def _find_swing_events(
        self, bars: tuple[Bar, ...], timeframe: str
    ) -> tuple[SwingEvent, ...]:
        """Detect confirmed fractal swings; math identical to legacy floats."""
        left = self._config.left_bars
        right = self._config.right_bars
        events: list[SwingEvent] = []
        if len(bars) < left + right + 1:
            return ()

        for index in range(left, len(bars) - right):
            candidate = bars[index]
            left_window = bars[index - left : index]
            right_window = bars[index + 1 : index + right + 1]
            confirmation_index = index + right
            confirmation_time = bars[confirmation_index].timestamp
            source_time = candidate.timestamp

            if all(candidate.high > bar.high for bar in left_window + right_window):
                events.append(
                    SwingEvent(
                        id=make_swing_id(timeframe, SwingKind.HIGH, index),
                        timeframe=timeframe,
                        kind=SwingKind.HIGH,
                        price=candidate.high,
                        index=index,
                        timestamp=source_time,
                        confirmation_index=confirmation_index,
                        confirmation_time=confirmation_time,
                    )
                )
            if all(candidate.low < bar.low for bar in left_window + right_window):
                events.append(
                    SwingEvent(
                        id=make_swing_id(timeframe, SwingKind.LOW, index),
                        timeframe=timeframe,
                        kind=SwingKind.LOW,
                        price=candidate.low,
                        index=index,
                        timestamp=source_time,
                        confirmation_index=confirmation_index,
                        confirmation_time=confirmation_time,
                    )
                )
        return tuple(events)

    def _find_swings(
        self, bars: tuple[Bar, ...]
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """Compatibility: price tuples only (same detection math)."""
        # Timeframe label unused for price-only projection.
        events = self._find_swing_events(bars, timeframe="_")
        highs = tuple(e.price for e in events if e.kind == SwingKind.HIGH)
        lows = tuple(e.price for e in events if e.kind == SwingKind.LOW)
        return highs, lows
