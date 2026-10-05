"""Strongly typed market-structure and feature-related enums/models."""

from dataclasses import dataclass
from enum import StrEnum


class MarketTrend(StrEnum):
    """Objective trend labels derived primarily from swing structure."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"
    UNKNOWN = "unknown"


class MarketPhase(StrEnum):
    """Descriptive phase labels for the current market structure."""

    TREND = "trend"
    PULLBACK = "pullback"
    RANGE = "range"
    COMPRESSION = "compression"
    REVERSAL = "reversal"


class RangeExpansionState(StrEnum):
    """Recent candle-body size versus historical body size.

    ``UNAVAILABLE`` means the ratio could not be computed (insufficient
    history or undefined baseline). It is not a market regime.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNAVAILABLE = "unavailable"


# Backward-compatible alias — prefer RangeExpansionState in new code.
MomentumState = RangeExpansionState


@dataclass(frozen=True)
class ComponentScore:
    """A scored analyzer component with a human-readable explanation."""

    name: str
    score: int
    reason: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TimeframeStructure:
    """Market-structure summary for a single timeframe."""

    timeframe: str
    trend: MarketTrend
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "timeframe": self.timeframe,
            "trend": self.trend.value,
            "reason": self.reason,
        }
