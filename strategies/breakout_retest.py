"""S002 Zone Breakout → Retest research strategy.

Hypothesis
----------
When price closes beyond a predefined support/resistance zone, a subsequent
retest of the broken zone boundary that rejects back in the breakout direction
can provide a measurable continuation opportunity.

V1 rules (causal, per-zone state)
---------------------------------
Breakout (no signal):
  - Bullish: close > zone.high → WAITING_FOR_BULLISH_RETEST (broken_level=zone.high)
  - Bearish: close < zone.low  → WAITING_FOR_BEARISH_RETEST (broken_level=zone.low)

Retest (emit signal), only after the breakout candle and within max_wait bars:
  - Bullish: low <= broken_level + tolerance AND close > broken_level → RETEST_ABOVE
  - Bearish: high >= broken_level - tolerance AND close < broken_level → RETEST_BELOW

Invalidation while waiting:
  - Bullish wait: close < zone.low → switch to WAITING_FOR_BEARISH_RETEST
  - Bearish wait: close > zone.high → switch to WAITING_FOR_BULLISH_RETEST

Expiry: no retest by breakout_index + max_wait → clear, then evaluate bar as IDLE.

New breakout while already waiting for the same zone:
  - Opposite-side close while waiting becomes the new breakout (above).
  - Continued move in the breakout direction does not reset max_wait.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from models.bar import Bar
from models.signal import Signal, SignalType
from models.zone import Zone, ZoneBook
from strategies.base_strategy import BaseStrategy


class BreakoutRetestState(StrEnum):
    IDLE = "idle"
    WAITING_FOR_BULLISH_RETEST = "waiting_for_bullish_retest"
    WAITING_FOR_BEARISH_RETEST = "waiting_for_bearish_retest"


@dataclass
class ZoneBreakoutRetestState:
    """Per-zone breakout-retest state."""

    zone_id: int
    status: BreakoutRetestState = BreakoutRetestState.IDLE
    broken_level: float | None = None
    breakout_index: int | None = None


class S002_BreakoutRetest(BaseStrategy):
    """Causal Zone Breakout → Retest strategy (research hypothesis S002)."""

    strategy_id = "S002"
    strategy_name = "BreakoutRetest"
    description = (
        "Zone breakout followed by a causal boundary retest within max_wait bars."
    )

    def __init__(
        self,
        zone_book: ZoneBook,
        *,
        tolerance: float = 0.0005,
        max_wait: int = 5,
    ) -> None:
        self.zone_book = zone_book
        self.tolerance = tolerance
        self.max_wait = max_wait
        self._zone_states: dict[int, ZoneBreakoutRetestState] = {}
        self._processed_count = 0
        self.reset()

    def reset(self) -> None:
        """Clear all per-zone waiting state and the processed-bar cursor."""
        self._zone_states = {
            zone.id: ZoneBreakoutRetestState(zone_id=zone.id)
            for zone in self.zone_book.zones
        }
        self._processed_count = 0

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        """Evaluate newly appended candles only (causal; no lookahead)."""
        if not candles:
            return []

        signals: list[Signal] = []
        start = self._processed_count
        if start > len(candles):
            # Defensive: history shrank unexpectedly — restart from beginning.
            start = 0
            self.reset()

        for index in range(start, len(candles)):
            bar = candles[index]
            if bar.symbol != self.zone_book.symbol:
                continue
            for zone in self.zone_book.zones:
                signal = self._evaluate_zone(zone, bar, index)
                if signal is not None:
                    signals.append(signal)

        self._processed_count = len(candles)
        return signals

    def _evaluate_zone(self, zone: Zone, bar: Bar, index: int) -> Signal | None:
        state = self._zone_states[zone.id]

        if state.status is BreakoutRetestState.WAITING_FOR_BULLISH_RETEST:
            return self._handle_waiting_bullish(zone, state, bar, index)
        if state.status is BreakoutRetestState.WAITING_FOR_BEARISH_RETEST:
            return self._handle_waiting_bearish(zone, state, bar, index)
        return self._handle_idle(zone, state, bar, index)

    def _handle_idle(
        self,
        zone: Zone,
        state: ZoneBreakoutRetestState,
        bar: Bar,
        index: int,
    ) -> Signal | None:
        if bar.close > zone.high:
            state.status = BreakoutRetestState.WAITING_FOR_BULLISH_RETEST
            state.broken_level = zone.high
            state.breakout_index = index
            return None
        if bar.close < zone.low:
            state.status = BreakoutRetestState.WAITING_FOR_BEARISH_RETEST
            state.broken_level = zone.low
            state.breakout_index = index
            return None
        return None

    def _handle_waiting_bullish(
        self,
        zone: Zone,
        state: ZoneBreakoutRetestState,
        bar: Bar,
        index: int,
    ) -> Signal | None:
        assert state.breakout_index is not None
        assert state.broken_level is not None

        # Breakout candle itself is never a retest.
        if index <= state.breakout_index:
            return None

        if index > state.breakout_index + self.max_wait:
            self._clear_state(state)
            # Expired wait; still allow this bar to open a new breakout.
            return self._handle_idle(zone, state, bar, index)

        # Invalidation: close back through the opposite zone side.
        if bar.close < zone.low:
            self._clear_state(state)
            # Opposite-side close is itself a bearish breakout.
            state.status = BreakoutRetestState.WAITING_FOR_BEARISH_RETEST
            state.broken_level = zone.low
            state.breakout_index = index
            return None

        broken_level = state.broken_level
        is_retest = (
            bar.low <= broken_level + self.tolerance and bar.close > broken_level
        )
        if is_retest:
            signal = self._build_signal(
                bar,
                zone,
                SignalType.RETEST_ABOVE,
                (
                    f"Bullish breakout retest confirmed at zone '{zone.name}' "
                    f"level {broken_level}"
                ),
            )
            self._clear_state(state)
            return signal

        # Price may continue higher while waiting — keep original breakout_index.
        return None

    def _handle_waiting_bearish(
        self,
        zone: Zone,
        state: ZoneBreakoutRetestState,
        bar: Bar,
        index: int,
    ) -> Signal | None:
        assert state.breakout_index is not None
        assert state.broken_level is not None

        if index <= state.breakout_index:
            return None

        if index > state.breakout_index + self.max_wait:
            self._clear_state(state)
            return self._handle_idle(zone, state, bar, index)

        if bar.close > zone.high:
            self._clear_state(state)
            state.status = BreakoutRetestState.WAITING_FOR_BULLISH_RETEST
            state.broken_level = zone.high
            state.breakout_index = index
            return None

        broken_level = state.broken_level
        is_retest = (
            bar.high >= broken_level - self.tolerance and bar.close < broken_level
        )
        if is_retest:
            signal = self._build_signal(
                bar,
                zone,
                SignalType.RETEST_BELOW,
                (
                    f"Bearish breakout retest confirmed at zone '{zone.name}' "
                    f"level {broken_level}"
                ),
            )
            self._clear_state(state)
            return signal

        # Price may continue lower while waiting — keep original breakout_index.
        return None

    @staticmethod
    def _clear_state(state: ZoneBreakoutRetestState) -> None:
        state.status = BreakoutRetestState.IDLE
        state.broken_level = None
        state.breakout_index = None

    @staticmethod
    def _build_signal(
        bar: Bar,
        zone: Zone,
        signal_type: SignalType,
        reason: str,
    ) -> Signal:
        return Signal(
            symbol=bar.symbol,
            signal=signal_type,
            zone_id=zone.id,
            price=bar.close,
            timestamp=bar.timestamp,
            reason=reason,
        )
