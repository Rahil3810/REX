"""Breakout strategy based on manually maintained support/resistance zones."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from core.logger import setup_logger
from models.bar import Bar
from models.signal import Signal, SignalType
from models.zone import Zone, ZoneBook
from strategies.base_strategy import BaseStrategy
from strategies.rules.breakout_rule import BreakoutRule

logger = setup_logger("breakout_strategy")


class PricePosition(StrEnum):
    """Price position relative to a zone."""

    ABOVE = "above"
    BELOW = "below"
    INSIDE = "inside"


@dataclass
class ZoneState:
    """Tracks the last known price position for a zone."""

    zone_id: int
    last_position: PricePosition | None = None
    was_inside: bool = False


@dataclass
class BreakoutStrategy(BaseStrategy):
    """
    Detect zone interactions: entry, breakout, and close outside.

    Does not place trades or apply risk management. Emits structured Signal
    objects for downstream research and measurement.
    """

    zone_book: ZoneBook
    _zone_states: dict[int, ZoneState] = field(default_factory=dict)
    _breakout_rule: BreakoutRule = field(
        default_factory=BreakoutRule,
        init=False,
        repr=False,
    )

    strategy_id = "CORE_ZONE_BREAKOUT"
    strategy_name = "Existing Zone Breakout"
    description = "Existing stateful support/resistance interaction strategy."

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Reset the strategy zone states."""
        self._zone_states.clear()
        for zone in self.zone_book.zones:
            self._zone_states[zone.id] = ZoneState(zone_id=zone.id)

    def evaluate(self, bar: Bar) -> list[Signal]:
        """
        Evaluate a single bar against all zones for the symbol.

        Returns a list of signals for any zone interactions detected on this bar.
        """
        if bar.symbol != self.zone_book.symbol:
            logger.warning(
                "Bar symbol %s does not match zone book symbol %s",
                bar.symbol,
                self.zone_book.symbol,
            )
            return []

        signals: list[Signal] = []

        for zone in self.zone_book.zones:
            zone_signals = self._evaluate_zone(bar, zone)
            signals.extend(zone_signals)

        return signals

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        """Implement the shared strategy interface without changing legacy behavior."""
        if not candles:
            return []
        return self.evaluate(candles[-1])

    def _evaluate_zone(self, bar: Bar, zone: Zone) -> list[Signal]:
        signals: list[Signal] = []
        state = self._zone_states[zone.id]

        current_position = self._resolve_position(bar.close, zone)
        previous_position = state.last_position

        if self._detect_zone_entry(bar, zone, previous_position, current_position):
            signals.append(
                self._build_signal(
                    bar=bar,
                    zone=zone,
                    signal_type=SignalType.ENTER_ZONE,
                    reason=f"Price entered zone '{zone.name}' ({zone.low}-{zone.high})",
                )
            )

        if self._detect_break_above(bar, zone, previous_position):
            signals.append(
                self._build_signal(
                    bar=bar,
                    zone=zone,
                    signal_type=SignalType.BREAK_ABOVE,
                    reason=f"Price broke above zone '{zone.name}' at {zone.high}",
                )
            )

        if self._detect_break_below(bar, zone, previous_position):
            signals.append(
                self._build_signal(
                    bar=bar,
                    zone=zone,
                    signal_type=SignalType.BREAK_BELOW,
                    reason=f"Price broke below zone '{zone.name}' at {zone.low}",
                )
            )

        if self._detect_close_outside(bar, zone):
            signals.append(
                self._build_signal(
                    bar=bar,
                    zone=zone,
                    signal_type=SignalType.CLOSE_OUTSIDE,
                    reason=self._close_outside_reason(bar.close, zone),
                )
            )

        state.last_position = current_position
        state.was_inside = current_position == PricePosition.INSIDE

        return signals

    def _resolve_position(self, price: float, zone: Zone) -> PricePosition:
        if zone.contains_price(price):
            return PricePosition.INSIDE
        if price > zone.high:
            return PricePosition.ABOVE
        return PricePosition.BELOW

    def _detect_zone_entry(
        self,
        bar: Bar,
        zone: Zone,
        previous_position: PricePosition | None,
        current_position: PricePosition,
    ) -> bool:
        if previous_position is None:
            return current_position == PricePosition.INSIDE and zone.overlaps_bar(
                bar.low, bar.high
            )
        return (
            previous_position != PricePosition.INSIDE
            and current_position == PricePosition.INSIDE
        )

    def _detect_break_above(
        self,
        bar: Bar,
        zone: Zone,
        previous_position: PricePosition | None,
    ) -> bool:
        return self._breakout_rule.detect_break_above(bar, zone, previous_position)

    def _detect_break_below(
        self,
        bar: Bar,
        zone: Zone,
        previous_position: PricePosition | None,
    ) -> bool:
        return self._breakout_rule.detect_break_below(bar, zone, previous_position)

    def _detect_close_outside(self, bar: Bar, zone: Zone) -> bool:
        return not zone.contains_price(bar.close)

    def _close_outside_reason(self, close: float, zone: Zone) -> str:
        if close > zone.high:
            return f"Close above zone '{zone.name}' at {zone.high}"
        return f"Close below zone '{zone.name}' at {zone.low}"

    def _build_signal(
        self,
        bar: Bar,
        zone: Zone,
        signal_type: SignalType,
        reason: str,
    ) -> Signal:
        signal = Signal(
            symbol=bar.symbol,
            signal=signal_type,
            zone_id=zone.id,
            price=bar.close,
            timestamp=bar.timestamp,
            reason=reason,
        )
        logger.info("Signal generated: %s", signal.to_dict())
        return signal
