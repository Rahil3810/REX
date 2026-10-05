"""PhaseView — experimental lifecycle/phase heuristic over existing features."""

from __future__ import annotations

from dataclasses import dataclass

from core.features.config import FeatureConfig, default_feature_config
from core.features.context import FeatureContext
from core.features.packs.base import PricePack, VolatilityPack
from core.features.types import (
    METHOD_PHASE_HEURISTIC_V1,
    PACK_PRICE,
    PACK_VOLATILITY,
    MethodId,
)
from core.features.views.base import UnsupportedMethodError, require_method_id
from core.features.views.trend import TrendView
from core.features.types import METHOD_TREND_MARKET_STRUCTURE_V1
from models.market_structure import MarketPhase, MarketTrend, RangeExpansionState


@dataclass(frozen=True)
class PhaseProjection:
    method_id: str
    phase: MarketPhase
    reason: str


class PhaseView:
    """Pure phase projection. Port of legacy PhaseAnalyzer heuristic."""

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or default_feature_config()
        self._trend_view = TrendView(self._config)

    def project(
        self, context: FeatureContext, method_id: MethodId | str
    ) -> PhaseProjection:
        method = require_method_id(method_id)
        if method != METHOD_PHASE_HEURISTIC_V1:
            raise UnsupportedMethodError(f"Unknown phase method_id: {method!r}")

        trend = self._trend_view.project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        volatility = context.require_pack(PACK_VOLATILITY, VolatilityPack)
        assert isinstance(volatility, VolatilityPack)
        price = context.require_pack(PACK_PRICE, PricePack)
        assert isinstance(price, PricePack)

        range_state = volatility.range_expansion.state
        closes = price.recent_closes.get(context.entry_timeframe, ())

        if range_state == RangeExpansionState.UNAVAILABLE:
            # Insufficient range evidence is not a regime — do not treat as
            # compression (which would fire if scored like LOW).
            if trend.trend in {MarketTrend.RANGING, MarketTrend.UNKNOWN}:
                phase = MarketPhase.RANGE
                reason = (
                    "Range expansion unavailable; trend is ranging or unknown."
                )
            elif _is_recent_pullback(
                trend.trend, closes, self._config.phase.pullback_recent_window
            ):
                phase = MarketPhase.PULLBACK
                reason = "Recent closes move against the structural trend."
            elif trend.structure_score >= self._config.phase.strong_trend_score_min:
                phase = MarketPhase.TREND
                reason = (
                    "Configured structure score meets strong-trend threshold."
                )
            else:
                phase = MarketPhase.REVERSAL
                reason = (
                    "Directional structure without strong-trend structure score."
                )
        elif (
            _range_expansion_score(range_state, self._config)
            <= self._config.phase.compression_range_expansion_score_max
        ):
            phase = MarketPhase.COMPRESSION
            reason = "Range expansion score indicates compression."
        elif trend.trend in {MarketTrend.RANGING, MarketTrend.UNKNOWN}:
            phase = MarketPhase.RANGE
            reason = "Trend is ranging or unknown."
        elif _is_recent_pullback(trend.trend, closes, self._config.phase.pullback_recent_window):
            phase = MarketPhase.PULLBACK
            reason = "Recent closes move against the structural trend."
        elif trend.structure_score >= self._config.phase.strong_trend_score_min:
            phase = MarketPhase.TREND
            reason = "Configured structure score meets strong-trend threshold."
        else:
            phase = MarketPhase.REVERSAL
            reason = "Directional structure without strong-trend structure score."

        return PhaseProjection(method_id=method, phase=phase, reason=reason)


def _range_expansion_score(
    state: RangeExpansionState, config: FeatureConfig
) -> int:
    """Map an observed range-expansion regime to a configured score.

    ``UNAVAILABLE`` is not a regime and must not be scored as NORMAL/LOW/HIGH.
    Callers must branch on ``UNAVAILABLE`` before invoking this helper.
    """
    if state == RangeExpansionState.UNAVAILABLE:
        raise ValueError(
            "RangeExpansionState.UNAVAILABLE has no regime score; "
            "callers must handle unavailable explicitly."
        )
    values = config.score_values
    return {
        RangeExpansionState.LOW: values.range_expansion_low,
        RangeExpansionState.NORMAL: values.range_expansion_normal,
        RangeExpansionState.HIGH: values.range_expansion_high,
    }[state]


def _is_recent_pullback(
    trend: MarketTrend, closes: tuple[float, ...], window: int
) -> bool:
    if len(closes) < window:
        return False
    recent = closes[-window:]
    if trend == MarketTrend.BULLISH:
        return all(recent[index] < recent[index - 1] for index in range(1, window))
    if trend == MarketTrend.BEARISH:
        return all(recent[index] > recent[index - 1] for index in range(1, window))
    return False
