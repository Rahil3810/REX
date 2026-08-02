"""Shared immutable state for market-structure analysis."""

from dataclasses import dataclass
from enum import StrEnum

from models.bar import Bar
from models.market_structure import MarketTrend, MomentumState


class ComponentId(StrEnum):
    """Stable identifiers for built-in market-structure score components."""

    PRICE_ACTION = "price_action"
    MULTI_TIMEFRAME = "multi_timeframe"
    TREND_STRUCTURE = "trend_structure"
    MOMENTUM = "momentum"
    EMA_ALIGNMENT = "ema_alignment"


@dataclass(frozen=True)
class StructureSnapshot:
    """Derived swing structure for one timeframe."""

    timeframe: str
    trend: MarketTrend
    reason: str
    swing_highs: tuple[float, ...]
    swing_lows: tuple[float, ...]


@dataclass(frozen=True)
class AnalyzerContext:
    """Immutable analysis data shared with component scorers."""

    symbol: str
    entry_timeframe: str
    bars_by_timeframe: dict[str, tuple[Bar, ...]]
    structures: dict[str, StructureSnapshot]
    entry_structure: StructureSnapshot
    momentum: MomentumState
    momentum_reason: str
    ema_alignment_reason: str
    ema_alignment_status: str
