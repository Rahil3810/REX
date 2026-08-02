"""Trend-state contract for Strategy V1 (placeholder)."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from core.market import Instrument
from core.market_structure.bos import StructureBreakEvent
from core.market_structure.choch import ChangeOfCharacterEvent
from core.market_structure.swing import SwingPoint
from models.bar import Bar


class TrendState(Enum):
    """Coarse directional state used by Strategy V1 consumers."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TrendStateSnapshot:
    """Trend classification at a point in the bar series."""

    state: TrendState
    reason: str = ""


class TrendStateAnalyzer(Protocol):
    """Derive trend state from structure inputs."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
        *,
        swings: Sequence[SwingPoint] = (),
        bos_events: Sequence[StructureBreakEvent] = (),
        choch_events: Sequence[ChangeOfCharacterEvent] = (),
    ) -> TrendStateSnapshot:
        """Return the current trend state (when implemented)."""


class PlaceholderTrendStateAnalyzer:
    """Reserved for Strategy V1 — always reports UNKNOWN."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
        *,
        swings: Sequence[SwingPoint] = (),
        bos_events: Sequence[StructureBreakEvent] = (),
        choch_events: Sequence[ChangeOfCharacterEvent] = (),
    ) -> TrendStateSnapshot:
        _ = bars, instrument, swings, bos_events, choch_events
        return TrendStateSnapshot(
            state=TrendState.UNKNOWN,
            reason="Trend-state analysis is not implemented yet (Strategy V1 placeholder).",
        )
