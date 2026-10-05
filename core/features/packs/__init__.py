"""Feature pack builders used by FeatureRepository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from core.features.config import FeatureConfig
from core.features.generators.range_expansion import RangeExpansionGenerator
from core.features.generators.returns import ReturnsGenerator
from core.features.generators.swings import SwingGenerator
from core.features.packs.base import (
    IndicatorPack,
    PricePack,
    SessionPack,
    StructurePack,
    VolatilityPack,
    ZonePack,
)
from core.features.types import (
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
    PACK_ZONES,
)
from core.market import Instrument
from core.session_manager import SessionManager
from models.bar import Bar

if TYPE_CHECKING:
    from core.indicators.indicator_engine import IndicatorEngine
    from core.zones.engine import ZoneEngine


def build_price_pack(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    instrument: Instrument,
    *,
    entry_timeframe: str,
) -> PricePack:
    returns = ReturnsGenerator().generate(
        bars_by_timeframe, instrument, entry_timeframe=entry_timeframe
    )
    recent_closes: dict[str, tuple[float, ...]] = {}
    for timeframe, bars in bars_by_timeframe.items():
        ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
        recent_closes[timeframe] = tuple(bar.close for bar in ordered)
    return PricePack(
        pack_id=PACK_PRICE,
        returns=returns,
        recent_closes=recent_closes,
    )


def build_structure_pack(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    instrument: Instrument,
    *,
    entry_timeframe: str,
    config: FeatureConfig,
    asof: datetime | None = None,
) -> StructurePack:
    swings = SwingGenerator(config.swing_detection).generate(
        bars_by_timeframe,
        instrument,
        entry_timeframe=entry_timeframe,
        asof=asof,
    )
    return StructurePack(pack_id=PACK_STRUCTURE, swings=swings)


def build_volatility_pack(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    instrument: Instrument,
    *,
    entry_timeframe: str,
    config: FeatureConfig,
    indicator_engine: IndicatorEngine | None = None,
) -> VolatilityPack:
    range_expansion = RangeExpansionGenerator(config.range_expansion).generate(
        bars_by_timeframe, instrument, entry_timeframe=entry_timeframe
    )
    atr_last = _atr_last(
        bars_by_timeframe.get(entry_timeframe, ()),
        config.indicators.atr_period,
        indicator_engine,
    )
    return VolatilityPack(
        pack_id=PACK_VOLATILITY,
        range_expansion=range_expansion,
        atr_last=atr_last,
    )


def build_indicator_pack(
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    *,
    entry_timeframe: str,
    config: FeatureConfig,
    indicator_engine: IndicatorEngine | None = None,
) -> IndicatorPack:
    empty = IndicatorPack(
        pack_id=PACK_INDICATORS,
        ema_fast_last=None,
        ema_slow_last=None,
        atr_last=None,
        rsi_last=None,
        macd_last=None,
        macd_signal_last=None,
        macd_histogram_last=None,
        relative_volume_last=None,
    )
    try:
        engine = indicator_engine or _default_indicator_engine()
    except ImportError:
        return empty
    bars = list(bars_by_timeframe.get(entry_timeframe, ()))
    if not bars:
        return empty

    indicators = config.indicators
    ema_fast_last = _series_last(
        engine.ema(bars, length=indicators.ema_fast_period)
    )
    ema_slow_last = _series_last(
        engine.ema(bars, length=indicators.ema_slow_period)
    )
    atr_last = _series_last(engine.atr(bars, length=indicators.atr_period))
    rsi_last = _series_last(engine.rsi(bars, length=indicators.rsi_period))
    macd_result = engine.macd(
        bars,
        fast=indicators.macd_fast_period,
        slow=indicators.macd_slow_period,
        signal=indicators.macd_signal_period,
    )
    relative_volume_last = _series_last(
        engine.relative_volume(bars, length=indicators.relative_volume_period)
    )
    return IndicatorPack(
        pack_id=PACK_INDICATORS,
        ema_fast_last=ema_fast_last,
        ema_slow_last=ema_slow_last,
        atr_last=atr_last,
        rsi_last=rsi_last,
        macd_last=_series_last(macd_result.macd),
        macd_signal_last=_series_last(macd_result.signal),
        macd_histogram_last=_series_last(macd_result.histogram),
        relative_volume_last=relative_volume_last,
    )


def build_zone_pack(
    instrument: Instrument,
    *,
    price: float | None,
    zone_engine: ZoneEngine | None,
) -> ZonePack:
    if zone_engine is None or price is None:
        return ZonePack(
            pack_id=PACK_ZONES,
            active_zones=(),
            nearest=None,
            inside_zone=False,
        )
    symbol = instrument.symbol
    return ZonePack(
        pack_id=PACK_ZONES,
        active_zones=zone_engine.active_zones(symbol, price),
        nearest=zone_engine.distance_to_nearest_zone(symbol, price),
        inside_zone=zone_engine.is_price_inside_zone(symbol, price),
    )


def build_session_pack(*, asof: datetime) -> SessionPack:
    info = SessionManager().get_current_session(asof)
    return SessionPack(
        pack_id=PACK_SESSION,
        session=info.session.value,
        overlap=info.overlap,
        high_liquidity=info.high_liquidity,
        active_sessions=tuple(session.value for session in info.active_sessions),
    )


def _default_indicator_engine() -> IndicatorEngine:
    from core.indicators.indicator_engine import IndicatorEngine
    from core.indicators.pandas_provider import PandasTAProvider

    return IndicatorEngine(PandasTAProvider())


def _atr_last(
    bars: Sequence[Bar],
    period: int,
    indicator_engine: IndicatorEngine | None,
) -> float | None:
    if not bars:
        return None
    try:
        engine = indicator_engine or _default_indicator_engine()
    except ImportError:
        return None
    return _series_last(engine.atr(list(bars), length=period))


def _series_last(series: object) -> float | None:
    try:
        if series is None or len(series) == 0:  # type: ignore[arg-type]
            return None
        value = series.iloc[-1]  # type: ignore[attr-defined]
        if value != value:  # NaN
            return None
        return float(value)
    except Exception:
        return None
