"""Orchestration for deterministic market-structure analysis."""

from collections.abc import Sequence
from pathlib import Path

from core.market_structure.confidence import ConfidenceCalculator
from core.market_structure.context import AnalyzerContext, ComponentId
from core.market_structure.ema import EmaAnalyzer
from core.market_structure.momentum import MomentumAnalyzer
from core.market_structure.phase import PhaseAnalyzer
from core.market_structure.scorers import (
    MarketStructureComponent,
    default_components,
)
from core.market_structure.trend import TrendAnalyzer
from core.market_structure_config import (
    MarketStructureAnalyzerConfig,
    load_market_structure_config,
)
from models.bar import Bar
from models.market_structure import (
    ComponentScore,
    MarketStructure,
    TimeframeStructure,
)


DEFAULT_MARKET_STRUCTURE_CONFIG = (
    Path(__file__).resolve().parents[2] / "config" / "market_structure.json"
)


class MarketStructureAnalyzer:
    """Orchestrate signal-free analysis of completed candle history."""

    def __init__(
        self,
        config: MarketStructureAnalyzerConfig | None = None,
        components: Sequence[MarketStructureComponent] | None = None,
    ) -> None:
        """Initialize the analyzer and its stateless collaborators.

        Args:
            config: Validated settings, or ``None`` to load the default JSON file.
            components: Optional scorer sequence replacing the built-in scorers.
        """
        self.config = config or load_market_structure_config(
            DEFAULT_MARKET_STRUCTURE_CONFIG
        )
        self.components: tuple[MarketStructureComponent, ...] = tuple(
            components if components is not None else default_components()
        )
        self._trend_analyzer = TrendAnalyzer(self.config.swing_detection)
        self._momentum_analyzer = MomentumAnalyzer(self.config.momentum)
        self._ema_analyzer = EmaAnalyzer(self.config.ema)
        self._phase_analyzer = PhaseAnalyzer(self.config.market_phase)
        self._confidence_calculator = ConfidenceCalculator(
            self.config.component_weights
        )

    def analyze(
        self,
        symbol: str,
        entry_timeframe: str,
        bars_by_timeframe: dict[str, Sequence[Bar]],
    ) -> MarketStructure:
        """Analyze completed candles and return objective market structure.

        Args:
            symbol: Instrument expected on every supplied candle.
            entry_timeframe: Primary timeframe to classify.
            bars_by_timeframe: Completed candle sequences keyed by timeframe.

        Returns:
            A deterministic, explainable market-structure snapshot.

        Raises:
            ValueError: If the entry timeframe is missing or candle inputs are
                invalid for the requested symbol.
        """
        normalized_bars = self._normalize_bars(symbol, bars_by_timeframe)
        if entry_timeframe not in normalized_bars:
            raise ValueError(f"Missing entry timeframe candles: {entry_timeframe}")

        structures = {
            timeframe: self._trend_analyzer.analyze(timeframe, bars)
            for timeframe, bars in normalized_bars.items()
        }
        entry_structure = structures[entry_timeframe]
        momentum, momentum_reason = self._momentum_analyzer.analyze(
            normalized_bars[entry_timeframe]
        )
        ema_status, ema_reason = self._ema_analyzer.analyze(
            entry_structure.trend,
            entry_timeframe,
            self.config.multi_timeframe_mapping.get(entry_timeframe, ()),
            normalized_bars,
        )
        context = AnalyzerContext(
            symbol=symbol,
            entry_timeframe=entry_timeframe,
            bars_by_timeframe=normalized_bars,
            structures=structures,
            entry_structure=entry_structure,
            momentum=momentum,
            momentum_reason=momentum_reason,
            ema_alignment_reason=ema_reason,
            ema_alignment_status=ema_status.value,
        )

        scores = self._score_components(context)
        confidence = self._confidence_calculator.calculate(scores)
        trend_strength = scores[ComponentId.TREND_STRUCTURE].score
        market_phase = self._phase_analyzer.analyze(
            trend=entry_structure.trend,
            trend_strength=trend_strength,
            momentum_score=scores[ComponentId.MOMENTUM].score,
            entry_bars=normalized_bars[entry_timeframe],
        )
        serialized_scores = {
            component_id.value: score for component_id, score in scores.items()
        }
        timeframe_structures = {
            timeframe: TimeframeStructure(
                timeframe=timeframe,
                trend=structure.trend,
                reason=structure.reason,
            )
            for timeframe, structure in structures.items()
        }

        return MarketStructure(
            symbol=symbol,
            entry_timeframe=entry_timeframe,
            trend=entry_structure.trend,
            market_phase=market_phase,
            momentum=momentum,
            trend_strength=trend_strength,
            confidence=confidence,
            price_action_score=scores[ComponentId.PRICE_ACTION],
            multi_timeframe_score=scores[ComponentId.MULTI_TIMEFRAME],
            trend_structure_score=scores[ComponentId.TREND_STRUCTURE],
            momentum_score=scores[ComponentId.MOMENTUM],
            ema_alignment_score=scores[ComponentId.EMA_ALIGNMENT],
            component_scores=serialized_scores,
            timeframe_structures=timeframe_structures,
            explanations=tuple(score.reason for score in scores.values()),
        )

    @staticmethod
    def _normalize_bars(
        symbol: str,
        bars_by_timeframe: dict[str, Sequence[Bar]],
    ) -> dict[str, tuple[Bar, ...]]:
        normalized: dict[str, tuple[Bar, ...]] = {}
        for timeframe, bars in bars_by_timeframe.items():
            if not timeframe:
                raise ValueError("Timeframe cannot be empty")
            symbol_bars = [bar for bar in bars if bar.symbol == symbol]
            if len(symbol_bars) != len(bars):
                raise ValueError(f"All bars for {timeframe} must match {symbol}")
            normalized[timeframe] = tuple(
                sorted(symbol_bars, key=lambda bar: bar.timestamp)
            )
        return normalized

    def _score_components(
        self, context: AnalyzerContext
    ) -> dict[ComponentId, ComponentScore]:
        return {
            ComponentId(component.name): component.score(context, self.config)
            for component in self.components
        }
