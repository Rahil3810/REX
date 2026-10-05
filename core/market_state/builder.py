"""Build MarketState from an existing FeatureContext using REX Views."""

from __future__ import annotations

from hashlib import sha256

from core.features.config import FeatureConfig, default_feature_config
from core.features.context import FeatureContext
from core.features.packs.base import (
    IndicatorPack,
    PricePack,
    SessionPack,
    VolatilityPack,
    ZonePack,
)
from core.features.types import (
    METHOD_LIQUIDITY_UNSUPPORTED,
    METHOD_MOMENTUM_TS_MOM_V1,
    METHOD_PHASE_HEURISTIC_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_VOLATILITY,
    PACK_ZONES,
    MethodId,
)
from core.features.views.base import UnsupportedMethodError
from core.features.views.momentum import MomentumView
from core.features.views.phase import PhaseView
from core.features.views.trend import TrendProjection, TrendView
from core.features.views.volatility import VolatilityView
from core.market_state.models import (
    MarketState,
    MarketStateIndicators,
    MarketStateLiquidity,
    MarketStateMetadata,
    MarketStateMomentum,
    MarketStatePhase,
    MarketStatePrice,
    MarketStateSession,
    MarketStateStructure,
    MarketStateVolatility,
    MarketStateZones,
    MultiTimeframeTrendSnapshot,
    NearestZoneSnapshot,
    SectionStatus,
    TimeframeSwingSnapshot,
    _zone_to_dict,
)
from models.market_structure import RangeExpansionState

MARKET_STATE_SCHEMA_VERSION = "1.0.0"


class MarketStateBuilder:
    """Convert FeatureContext + method IDs into a deterministic MarketState."""

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or default_feature_config()
        self._trend_view = TrendView(self._config)
        self._momentum_view = MomentumView()
        self._volatility_view = VolatilityView()
        self._phase_view = PhaseView(self._config)

    def build(
        self,
        context: FeatureContext,
        *,
        trend_method_id: MethodId | str = METHOD_TREND_MARKET_STRUCTURE_V1,
        momentum_method_id: MethodId | str = METHOD_MOMENTUM_TS_MOM_V1,
        volatility_method_id: MethodId | str = METHOD_VOLATILITY_RANGE_EXPANSION_V1,
        phase_method_id: MethodId | str = METHOD_PHASE_HEURISTIC_V1,
        liquidity_method_id: MethodId | str = METHOD_LIQUIDITY_UNSUPPORTED,
    ) -> MarketState:
        method_ids = {
            "trend": str(trend_method_id),
            "momentum": str(momentum_method_id),
            "volatility": str(volatility_method_id),
            "phase": str(phase_method_id),
            "liquidity": str(liquidity_method_id),
        }
        metadata = MarketStateMetadata(
            schema_version=MARKET_STATE_SCHEMA_VERSION,
            schema_hash=_market_state_schema_hash(method_ids),
            context_schema_hash=context.schema_hash,
            instrument=str(context.instrument.symbol),
            asof=context.asof,
            entry_timeframe=context.entry_timeframe,
            trend_method_id=method_ids["trend"],
            momentum_method_id=method_ids["momentum"],
            volatility_method_id=method_ids["volatility"],
            phase_method_id=method_ids["phase"],
            liquidity_method_id=method_ids["liquidity"],
        )
        return MarketState(
            metadata=metadata,
            price=_build_price(context),
            structure=_build_structure(
                context, self._trend_view, trend_method_id=method_ids["trend"]
            ),
            momentum=_build_momentum(
                context, self._momentum_view, momentum_method_id=method_ids["momentum"]
            ),
            phase=_build_phase(
                context, self._phase_view, phase_method_id=method_ids["phase"]
            ),
            indicators=_build_indicators(context),
            volatility=_build_volatility(
                context,
                self._volatility_view,
                volatility_method_id=method_ids["volatility"],
            ),
            zones=_build_zones(context),
            session=_build_session(context),
            liquidity=_build_liquidity(liquidity_method_id=method_ids["liquidity"]),
        )


def _market_state_schema_hash(method_ids: dict[str, str]) -> str:
    payload = MARKET_STATE_SCHEMA_VERSION + "|" + "|".join(
        f"{key}={method_ids[key]}" for key in sorted(method_ids)
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_price(context: FeatureContext) -> MarketStatePrice:
    entry_bars = context.bars_by_timeframe.get(context.entry_timeframe, ())
    if entry_bars:
        return MarketStatePrice(
            status=SectionStatus.AVAILABLE,
            current=float(entry_bars[-1].close),
        )

    if PACK_PRICE in context.packs:
        price_pack = context.require_pack(PACK_PRICE, PricePack)
        assert isinstance(price_pack, PricePack)
        closes = price_pack.recent_closes.get(context.entry_timeframe, ())
        if closes:
            return MarketStatePrice(
                status=SectionStatus.AVAILABLE,
                current=float(closes[-1]),
            )

    return MarketStatePrice(
        status=SectionStatus.UNAVAILABLE,
        current=None,
        reason="No entry-timeframe bars or closes available.",
    )


def _build_structure(
    context: FeatureContext,
    trend_view: TrendView,
    *,
    trend_method_id: str,
) -> MarketStateStructure:
    try:
        projection = trend_view.project(context, trend_method_id)
    except (KeyError, TypeError, UnsupportedMethodError) as exc:
        return MarketStateStructure(
            status=SectionStatus.UNAVAILABLE,
            method_id=trend_method_id,
            trend=None,
            structure_score=None,
            reason=str(exc),
            entry_timeframe=None,
            by_timeframe=(),
            multi_timeframe=None,
        )

    assert isinstance(projection, TrendProjection)
    by_timeframe = tuple(_timeframe_snapshot(item) for item in projection.by_timeframe.values())
    entry = projection.by_timeframe.get(context.entry_timeframe)
    return MarketStateStructure(
        status=SectionStatus.AVAILABLE,
        method_id=projection.method_id,
        trend=projection.trend.value,
        structure_score=projection.structure_score,
        reason=projection.reason,
        entry_timeframe=_timeframe_snapshot(entry) if entry else None,
        by_timeframe=by_timeframe,
        multi_timeframe=MultiTimeframeTrendSnapshot(
            score=projection.multi_timeframe.score,
            reason=projection.multi_timeframe.reason,
        ),
    )


def _timeframe_snapshot(projection: object) -> TimeframeSwingSnapshot:
    from core.features.views.trend import TimeframeTrendProjection

    assert isinstance(projection, TimeframeTrendProjection)
    return TimeframeSwingSnapshot(
        timeframe=projection.timeframe,
        swing_highs=projection.swing_highs,
        swing_lows=projection.swing_lows,
        trend=projection.trend.value,
        reason=projection.reason,
        swings=tuple(event.to_dict() for event in projection.swings),
    )


def _build_momentum(
    context: FeatureContext,
    momentum_view: MomentumView,
    *,
    momentum_method_id: str,
) -> MarketStateMomentum:
    try:
        projection = momentum_view.project(context, momentum_method_id)
    except (KeyError, TypeError, UnsupportedMethodError) as exc:
        return MarketStateMomentum(
            status=SectionStatus.UNAVAILABLE,
            method_id=momentum_method_id,
            direction=None,
            strength=None,
            reason=str(exc),
        )
    return MarketStateMomentum(
        status=SectionStatus.AVAILABLE,
        method_id=projection.method_id,
        direction=projection.direction.value,
        strength=projection.strength,
        reason=projection.reason,
    )


def _build_phase(
    context: FeatureContext,
    phase_view: PhaseView,
    *,
    phase_method_id: str,
) -> MarketStatePhase:
    try:
        projection = phase_view.project(context, phase_method_id)
    except (KeyError, TypeError, UnsupportedMethodError) as exc:
        return MarketStatePhase(
            status=SectionStatus.UNAVAILABLE,
            method_id=phase_method_id,
            phase=None,
            reason=str(exc),
        )
    return MarketStatePhase(
        status=SectionStatus.AVAILABLE,
        method_id=projection.method_id,
        phase=projection.phase.value,
        reason=projection.reason,
    )


def _build_indicators(context: FeatureContext) -> MarketStateIndicators:
    if PACK_INDICATORS not in context.packs:
        return MarketStateIndicators(
            status=SectionStatus.UNAVAILABLE,
            rsi=None,
            macd=None,
            macd_signal=None,
            macd_histogram=None,
            relative_volume=None,
            ema_fast=None,
            ema_slow=None,
            atr=None,
            reason="Indicator pack was not materialized.",
        )

    pack = context.require_pack(PACK_INDICATORS, IndicatorPack)
    assert isinstance(pack, IndicatorPack)
    return MarketStateIndicators(
        status=SectionStatus.AVAILABLE,
        rsi=pack.rsi_last,
        macd=pack.macd_last,
        macd_signal=pack.macd_signal_last,
        macd_histogram=pack.macd_histogram_last,
        relative_volume=pack.relative_volume_last,
        ema_fast=pack.ema_fast_last,
        ema_slow=pack.ema_slow_last,
        atr=pack.atr_last,
    )


def _build_volatility(
    context: FeatureContext,
    volatility_view: VolatilityView,
    *,
    volatility_method_id: str,
) -> MarketStateVolatility:
    atr: float | None = None
    if PACK_VOLATILITY in context.packs:
        vol_pack = context.require_pack(PACK_VOLATILITY, VolatilityPack)
        assert isinstance(vol_pack, VolatilityPack)
        atr = vol_pack.atr_last
    elif PACK_INDICATORS in context.packs:
        indicator_pack = context.require_pack(PACK_INDICATORS, IndicatorPack)
        assert isinstance(indicator_pack, IndicatorPack)
        atr = indicator_pack.atr_last

    try:
        projection = volatility_view.project(context, volatility_method_id)
    except (KeyError, TypeError, UnsupportedMethodError) as exc:
        return MarketStateVolatility(
            status=SectionStatus.UNAVAILABLE,
            method_id=volatility_method_id,
            range_expansion_state=None,
            range_expansion_ratio=None,
            atr=atr,
            reason=str(exc),
        )

    if projection.state == RangeExpansionState.UNAVAILABLE:
        return MarketStateVolatility(
            status=SectionStatus.UNAVAILABLE,
            method_id=projection.method_id,
            range_expansion_state=projection.state.value,
            range_expansion_ratio=None,
            atr=atr,
            reason=projection.reason,
        )

    return MarketStateVolatility(
        status=SectionStatus.AVAILABLE,
        method_id=projection.method_id,
        range_expansion_state=projection.state.value,
        range_expansion_ratio=projection.ratio,
        atr=atr,
        reason=projection.reason,
    )


def _build_zones(context: FeatureContext) -> MarketStateZones:
    if PACK_ZONES not in context.packs:
        return MarketStateZones(
            status=SectionStatus.UNAVAILABLE,
            active_zones=(),
            nearest=None,
            inside_zone=None,
            reason="Zone pack was not materialized.",
        )

    pack = context.require_pack(PACK_ZONES, ZonePack)
    assert isinstance(pack, ZonePack)
    nearest = None
    if pack.nearest is not None:
        nearest = NearestZoneSnapshot(
            zone_id=pack.nearest.zone.id,
            name=pack.nearest.zone.name,
            timeframe=pack.nearest.zone.timeframe,
            strength=pack.nearest.zone.strength,
            side=pack.nearest.side,
            distance_price=pack.nearest.distance_price,
            distance_pips=pack.nearest.distance_pips,
            source=pack.nearest.zone.source.value,
        )
    return MarketStateZones(
        status=SectionStatus.AVAILABLE,
        active_zones=tuple(_zone_to_dict(zone) for zone in pack.active_zones),
        nearest=nearest,
        inside_zone=pack.inside_zone,
    )


def _build_session(context: FeatureContext) -> MarketStateSession:
    if PACK_SESSION not in context.packs:
        return MarketStateSession(
            status=SectionStatus.UNAVAILABLE,
            session=None,
            active_sessions=(),
            overlap=None,
            high_liquidity=None,
            reason="Session pack was not materialized.",
        )

    pack = context.require_pack(PACK_SESSION, SessionPack)
    assert isinstance(pack, SessionPack)
    return MarketStateSession(
        status=SectionStatus.AVAILABLE,
        session=pack.session,
        active_sessions=pack.active_sessions,
        overlap=pack.overlap,
        high_liquidity=pack.high_liquidity,
    )


def _build_liquidity(*, liquidity_method_id: str) -> MarketStateLiquidity:
    return MarketStateLiquidity(
        status=SectionStatus.UNSUPPORTED,
        method_id=liquidity_method_id,
        reason=(
            "Liquidity analysis is not implemented in Phase 1. "
            "No liquidity pack is materialized."
        ),
    )
