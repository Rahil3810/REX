"""Strongly typed market-structure analysis models."""

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


class MomentumState(StrEnum):
    """Momentum labels based on recent candle bodies versus historical bodies."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


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


@dataclass(frozen=True)
class MarketStructure:
    """
    Deterministic market-structure snapshot.

    This model describes observed market structure only. It contains no trade
    direction, order instruction, position sizing, or risk-management decision.
    """

    symbol: str
    entry_timeframe: str
    trend: MarketTrend
    market_phase: MarketPhase
    momentum: MomentumState
    trend_strength: int
    confidence: int
    price_action_score: ComponentScore
    multi_timeframe_score: ComponentScore
    trend_structure_score: ComponentScore
    momentum_score: ComponentScore
    ema_alignment_score: ComponentScore
    component_scores: dict[str, ComponentScore]
    timeframe_structures: dict[str, TimeframeStructure]
    explanations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "entry_timeframe": self.entry_timeframe,
            "trend": self.trend.value,
            "market_phase": self.market_phase.value,
            "momentum": self.momentum.value,
            "trend_strength": self.trend_strength,
            "confidence": self.confidence,
            "price_action_score": self.price_action_score.to_dict(),
            "multi_timeframe_score": self.multi_timeframe_score.to_dict(),
            "trend_structure_score": self.trend_structure_score.to_dict(),
            "momentum_score": self.momentum_score.to_dict(),
            "ema_alignment_score": self.ema_alignment_score.to_dict(),
            "component_scores": {
                name: score.to_dict()
                for name, score in self.component_scores.items()
            },
            "timeframe_structures": {
                timeframe: structure.to_dict()
                for timeframe, structure in self.timeframe_structures.items()
            },
            "explanations": list(self.explanations),
        }
