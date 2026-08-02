"""Backward-compatible imports for the market-structure analyzer package."""

from core.market_structure import (
    DEFAULT_MARKET_STRUCTURE_CONFIG,
    AnalyzerContext,
    ComponentId,
    EmaAlignmentScorer,
    MarketStructureAnalyzer,
    MarketStructureComponent,
    MomentumScorer,
    MultiTimeframeScorer,
    PriceActionScorer,
    StructureSnapshot,
    TrendStructureScorer,
)

__all__ = [
    "AnalyzerContext",
    "ComponentId",
    "DEFAULT_MARKET_STRUCTURE_CONFIG",
    "EmaAlignmentScorer",
    "MarketStructureAnalyzer",
    "MarketStructureComponent",
    "MomentumScorer",
    "MultiTimeframeScorer",
    "PriceActionScorer",
    "StructureSnapshot",
    "TrendStructureScorer",
]
