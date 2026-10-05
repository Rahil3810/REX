"""Frozen feature pack containers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from core.features.generators.range_expansion import RangeExpansionFeatures
from core.features.generators.returns import ReturnFeatures
from core.features.generators.swings import SwingFeatures
from core.features.types import PackId
from core.zones.types import ZoneDistance
from models.zone import Zone


class FeaturePack(Protocol):
    """Marker for immutable pack payloads stored on FeatureContext."""

    pack_id: PackId


@dataclass(frozen=True)
class PricePack:
    pack_id: PackId
    returns: ReturnFeatures
    recent_closes: Mapping[str, tuple[float, ...]]


@dataclass(frozen=True)
class VolatilityPack:
    pack_id: PackId
    range_expansion: RangeExpansionFeatures
    atr_last: float | None


@dataclass(frozen=True)
class IndicatorPack:
    pack_id: PackId
    ema_fast_last: float | None
    ema_slow_last: float | None
    atr_last: float | None
    rsi_last: float | None
    macd_last: float | None
    macd_signal_last: float | None
    macd_histogram_last: float | None
    relative_volume_last: float | None


@dataclass(frozen=True)
class ZonePack:
    pack_id: PackId
    active_zones: tuple[Zone, ...]
    nearest: ZoneDistance | None
    inside_zone: bool


@dataclass(frozen=True)
class SessionPack:
    pack_id: PackId
    session: str
    overlap: bool
    high_liquidity: bool
    active_sessions: tuple[str, ...]


@dataclass(frozen=True)
class StructurePack:
    pack_id: PackId
    swings: SwingFeatures
