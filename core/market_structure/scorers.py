"""Pluggable score components for market-structure analysis."""

from typing import Protocol

from core.market_structure.context import AnalyzerContext, ComponentId
from core.market_structure.ema import EmaAlignmentStatus
from core.market_structure_config import MarketStructureAnalyzerConfig
from models.market_structure import ComponentScore, MarketTrend, MomentumState


class MarketStructureComponent(Protocol):
    """Interface implemented by market-structure score components."""

    name: ComponentId

    def score(
        self,
        context: AnalyzerContext,
        config: MarketStructureAnalyzerConfig,
    ) -> ComponentScore:
        """Score one analysis component.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            A numeric score with an explanatory reason.
        """
        ...


class PriceActionScorer:
    """Score observed price action from entry-timeframe swing trend."""

    name = ComponentId.PRICE_ACTION

    def score(
        self, context: AnalyzerContext, config: MarketStructureAnalyzerConfig
    ) -> ComponentScore:
        """Score price action from the derived trend.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            The price-action component score.
        """
        trend = context.entry_structure.trend
        values = config.component_score_values
        if trend in {MarketTrend.BULLISH, MarketTrend.BEARISH}:
            score = values.aligned
        elif trend == MarketTrend.RANGING:
            score = values.neutral
        else:
            score = values.unknown
        return ComponentScore(self.name.value, score, context.entry_structure.reason)


class TrendStructureScorer:
    """Score whether swing highs and lows form coherent structure."""

    name = ComponentId.TREND_STRUCTURE

    def score(
        self, context: AnalyzerContext, config: MarketStructureAnalyzerConfig
    ) -> ComponentScore:
        """Score swing-structure coherence.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            The trend-structure component score.
        """
        trend = context.entry_structure.trend
        scoring = config.trend_scoring
        if trend in {MarketTrend.BULLISH, MarketTrend.BEARISH}:
            score = scoring.aligned_structure_score
        elif trend == MarketTrend.RANGING:
            score = scoring.ranging_score
        else:
            score = scoring.unknown_score
        return ComponentScore(self.name.value, score, context.entry_structure.reason)


class MomentumScorer:
    """Score body-size momentum versus historical body size."""

    name = ComponentId.MOMENTUM

    def score(
        self, context: AnalyzerContext, config: MarketStructureAnalyzerConfig
    ) -> ComponentScore:
        """Score the derived momentum state.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            The momentum component score.
        """
        values = config.component_score_values
        score_by_state = {
            MomentumState.LOW: values.momentum_low,
            MomentumState.NORMAL: values.momentum_normal,
            MomentumState.HIGH: values.momentum_high,
        }
        return ComponentScore(
            self.name.value, score_by_state[context.momentum], context.momentum_reason
        )


class EmaAlignmentScorer:
    """Score EMA alignment as confirmation, never primary trend evidence."""

    name = ComponentId.EMA_ALIGNMENT

    def score(
        self, context: AnalyzerContext, config: MarketStructureAnalyzerConfig
    ) -> ComponentScore:
        """Score EMA confirmation of the swing-derived trend.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            The EMA-alignment component score.
        """
        values = config.component_score_values
        scores = {
            EmaAlignmentStatus.ALIGNED: values.aligned,
            EmaAlignmentStatus.PARTIAL: values.partial,
            EmaAlignmentStatus.NEUTRAL: values.neutral,
            EmaAlignmentStatus.UNKNOWN: values.unknown,
        }
        status = EmaAlignmentStatus(context.ema_alignment_status)
        return ComponentScore(
            self.name.value, scores[status], context.ema_alignment_reason
        )


class MultiTimeframeScorer:
    """Score higher-timeframe agreement with the entry trend."""

    name = ComponentId.MULTI_TIMEFRAME

    def score(
        self, context: AnalyzerContext, config: MarketStructureAnalyzerConfig
    ) -> ComponentScore:
        """Score configured higher-timeframe trend agreement.

        Args:
            context: Shared immutable analyzer context.
            config: Validated market-structure configuration.

        Returns:
            The multi-timeframe component score.
        """
        higher_timeframes = config.multi_timeframe_mapping.get(
            context.entry_timeframe, ()
        )
        values = config.component_score_values
        if not higher_timeframes:
            return ComponentScore(
                self.name.value,
                values.neutral,
                f"No higher-timeframe confirmations configured for "
                f"{context.entry_timeframe}.",
            )

        missing = [tf for tf in higher_timeframes if tf not in context.structures]
        available = [
            context.structures[tf]
            for tf in higher_timeframes
            if tf in context.structures
        ]
        if not available:
            return ComponentScore(
                self.name.value,
                values.unknown,
                "No configured higher-timeframe candle history was supplied: "
                f"{', '.join(higher_timeframes)}.",
            )

        entry_trend = context.entry_structure.trend
        aligned = [
            structure
            for structure in available
            if structure.trend == entry_trend
            and entry_trend not in {MarketTrend.RANGING, MarketTrend.UNKNOWN}
        ]
        if len(aligned) == len(available) and not missing:
            score = values.aligned
            reason = (
                "All configured higher timeframes agree with the entry timeframe: "
                f"{', '.join(structure.timeframe for structure in aligned)}."
            )
        elif aligned:
            score = values.partial
            reason = (
                "Some higher timeframes agree with the entry timeframe: "
                f"{', '.join(structure.timeframe for structure in aligned)}."
            )
            if missing:
                reason += f" Missing: {', '.join(missing)}."
        else:
            score = values.neutral
            compared = ", ".join(
                f"{structure.timeframe}={structure.trend.value}"
                for structure in available
            )
            reason = (
                "Configured higher timeframes do not align with the entry "
                f"timeframe trend. Compared: {compared}."
            )
            if missing:
                reason += f" Missing: {', '.join(missing)}."
        return ComponentScore(self.name.value, score, reason)


def default_components() -> tuple[MarketStructureComponent, ...]:
    """Create the built-in scorer sequence.

    Returns:
        Scorers in the established output and explanation order.
    """
    return (
        PriceActionScorer(),
        MultiTimeframeScorer(),
        TrendStructureScorer(),
        MomentumScorer(),
        EmaAlignmentScorer(),
    )
