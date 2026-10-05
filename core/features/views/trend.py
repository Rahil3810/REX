"""TrendView — versioned interpretations of structure features."""

from __future__ import annotations

from dataclasses import dataclass

from core.features.config import FeatureConfig, default_feature_config
from core.features.context import FeatureContext
from core.features.generators.swings import SwingEvent, TimeframeSwings
from core.features.packs.base import StructurePack
from core.features.types import (
    METHOD_TREND_DRIFT_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    PACK_STRUCTURE,
    MethodId,
)
from core.features.views.base import UnsupportedMethodError, require_method_id
from models.market_structure import MarketTrend


@dataclass(frozen=True)
class TimeframeTrendProjection:
    timeframe: str
    trend: MarketTrend
    reason: str
    swing_highs: tuple[float, ...]
    swing_lows: tuple[float, ...]
    swings: tuple[SwingEvent, ...] = ()


@dataclass(frozen=True)
class MultiTimeframeAgreement:
    score: int
    reason: str


@dataclass(frozen=True)
class TrendProjection:
    """Entry-timeframe trend projection for a named method.

    ``structure_score`` is a **configured categorical score** from
    ``FeatureConfig.trend_strength`` (aligned / ranging / unknown). It is
    **not** confidence, probability, trend magnitude, or signal quality.
    """

    method_id: str
    trend: MarketTrend
    reason: str
    structure_score: int
    by_timeframe: dict[str, TimeframeTrendProjection]
    multi_timeframe: MultiTimeframeAgreement


class TrendView:
    """Pure trend projections. Requires an explicit method_id."""

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or default_feature_config()

    def project(
        self, context: FeatureContext, method_id: MethodId | str
    ) -> TrendProjection:
        method = require_method_id(method_id)
        if method == METHOD_TREND_MARKET_STRUCTURE_V1:
            return self._market_structure_v1(context)
        if method == METHOD_TREND_DRIFT_V1:
            raise UnsupportedMethodError(
                f"Trend method {method!r} is reserved but not implemented yet"
            )
        raise UnsupportedMethodError(f"Unknown trend method_id: {method!r}")

    def _market_structure_v1(self, context: FeatureContext) -> TrendProjection:
        structure = context.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(structure, StructurePack)
        minimum = self._config.swing_detection.minimum_swings
        by_timeframe: dict[str, TimeframeTrendProjection] = {}
        for timeframe, swings in structure.swings.by_timeframe.items():
            projection = _classify_swings(swings, minimum)
            by_timeframe[timeframe] = projection

        entry = by_timeframe.get(context.entry_timeframe)
        if entry is None:
            raise KeyError(
                f"No structure features for entry timeframe {context.entry_timeframe}"
            )

        structure_score = _structure_score(entry.trend, self._config)
        mtf = _multi_timeframe_agreement(
            entry_timeframe=context.entry_timeframe,
            entry_trend=entry.trend,
            by_timeframe=by_timeframe,
            mapping=dict(context.multi_timeframe_mapping),
            config=self._config,
        )
        return TrendProjection(
            method_id=str(METHOD_TREND_MARKET_STRUCTURE_V1),
            trend=entry.trend,
            reason=entry.reason,
            structure_score=structure_score,
            by_timeframe=by_timeframe,
            multi_timeframe=mtf,
        )


def _classify_swings(
    swings: TimeframeSwings, minimum_swings: int
) -> TimeframeTrendProjection:
    timeframe = swings.timeframe
    swing_highs = swings.swing_highs
    swing_lows = swings.swing_lows
    events = swings.swings
    if len(swing_highs) < minimum_swings or len(swing_lows) < minimum_swings:
        return TimeframeTrendProjection(
            timeframe=timeframe,
            trend=MarketTrend.UNKNOWN,
            reason=(
                f"Insufficient completed swing points on {timeframe}: "
                f"{len(swing_highs)} highs and {len(swing_lows)} lows found."
            ),
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            swings=events,
        )

    recent_highs = swing_highs[-minimum_swings:]
    recent_lows = swing_lows[-minimum_swings:]
    highs_rising = all(
        recent_highs[index] > recent_highs[index - 1]
        for index in range(1, len(recent_highs))
    )
    lows_rising = all(
        recent_lows[index] > recent_lows[index - 1]
        for index in range(1, len(recent_lows))
    )
    highs_falling = all(
        recent_highs[index] < recent_highs[index - 1]
        for index in range(1, len(recent_highs))
    )
    lows_falling = all(
        recent_lows[index] < recent_lows[index - 1]
        for index in range(1, len(recent_lows))
    )

    if highs_rising and lows_rising:
        trend = MarketTrend.BULLISH
        reason = (
            f"Detected consecutive higher highs {recent_highs} and "
            f"higher lows {recent_lows} on {timeframe}."
        )
    elif highs_falling and lows_falling:
        trend = MarketTrend.BEARISH
        reason = (
            f"Detected consecutive lower highs {recent_highs} and "
            f"lower lows {recent_lows} on {timeframe}."
        )
    else:
        trend = MarketTrend.RANGING
        reason = (
            f"Swing highs {recent_highs} and swing lows {recent_lows} "
            f"do not form a clean directional structure on {timeframe}."
        )
    return TimeframeTrendProjection(
        timeframe=timeframe,
        trend=trend,
        reason=reason,
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        swings=events,
    )


def _structure_score(trend: MarketTrend, config: FeatureConfig) -> int:
    """Return the configured categorical structure score for ``trend``.

    This is a lookup of ``aligned_structure_score`` / ``ranging_score`` /
    ``unknown_score``. It is not confidence, probability, or magnitude.
    """
    scoring = config.trend_strength
    if trend in {MarketTrend.BULLISH, MarketTrend.BEARISH}:
        return scoring.aligned_structure_score
    if trend == MarketTrend.RANGING:
        return scoring.ranging_score
    return scoring.unknown_score


# Backward-compatible alias for audit/verification imports during rename.
_trend_strength = _structure_score


def _multi_timeframe_agreement(
    *,
    entry_timeframe: str,
    entry_trend: MarketTrend,
    by_timeframe: dict[str, TimeframeTrendProjection],
    mapping: dict[str, tuple[str, ...]],
    config: FeatureConfig,
) -> MultiTimeframeAgreement:
    higher_timeframes = mapping.get(entry_timeframe, ())
    values = config.score_values
    if not higher_timeframes:
        return MultiTimeframeAgreement(
            score=values.neutral,
            reason=(
                f"No higher-timeframe confirmations configured for {entry_timeframe}."
            ),
        )

    missing = [tf for tf in higher_timeframes if tf not in by_timeframe]
    available = [by_timeframe[tf] for tf in higher_timeframes if tf in by_timeframe]
    if not available:
        return MultiTimeframeAgreement(
            score=values.unknown,
            reason=(
                "No configured higher-timeframe candle history was supplied: "
                f"{', '.join(higher_timeframes)}."
            ),
        )

    aligned = [
        structure
        for structure in available
        if structure.trend == entry_trend
        and entry_trend not in {MarketTrend.RANGING, MarketTrend.UNKNOWN}
    ]
    if len(aligned) == len(available) and not missing:
        return MultiTimeframeAgreement(
            score=values.aligned,
            reason=(
                "All configured higher timeframes agree with the entry timeframe: "
                f"{', '.join(structure.timeframe for structure in aligned)}."
            ),
        )
    if aligned:
        reason = (
            "Some higher timeframes agree with the entry timeframe: "
            f"{', '.join(structure.timeframe for structure in aligned)}."
        )
        if missing:
            reason += f" Missing: {', '.join(missing)}."
        return MultiTimeframeAgreement(score=values.partial, reason=reason)

    compared = ", ".join(
        f"{structure.timeframe}={structure.trend.value}" for structure in available
    )
    reason = (
        "Configured higher timeframes do not align with the entry "
        f"timeframe trend. Compared: {compared}."
    )
    if missing:
        reason += f" Missing: {', '.join(missing)}."
    return MultiTimeframeAgreement(score=values.neutral, reason=reason)
