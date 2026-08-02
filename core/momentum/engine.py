"""Momentum engine package — Strategy V1 placeholder (no trading logic)."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from core.market import Instrument
from models.bar import Bar


class MomentumBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MomentumSnapshot:
    """Reserved momentum context for a bar series."""

    bias: MomentumBias = MomentumBias.UNKNOWN
    reason: str = "Momentum analysis is not implemented yet."


class MomentumEngine(Protocol):
    """Future momentum / displacement queries."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
    ) -> MomentumSnapshot:
        """Return a momentum snapshot (when implemented)."""


class PlaceholderMomentumEngine:
    """Reserved for Strategy V1 — no momentum logic yet."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
    ) -> MomentumSnapshot:
        _ = bars, instrument
        return MomentumSnapshot()
