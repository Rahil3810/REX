"""Immutable AI-facing market state models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from models.zone import Zone


class SectionStatus(StrEnum):
    """Whether a MarketState section was materialized from FeatureContext."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MarketStateMetadata:
    schema_version: str
    schema_hash: str
    context_schema_hash: str
    instrument: str
    asof: datetime
    entry_timeframe: str
    trend_method_id: str
    momentum_method_id: str
    volatility_method_id: str
    phase_method_id: str
    liquidity_method_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "context_schema_hash": self.context_schema_hash,
            "instrument": self.instrument,
            "asof": self.asof.isoformat(),
            "entry_timeframe": self.entry_timeframe,
            "trend_method_id": self.trend_method_id,
            "momentum_method_id": self.momentum_method_id,
            "volatility_method_id": self.volatility_method_id,
            "phase_method_id": self.phase_method_id,
            "liquidity_method_id": self.liquidity_method_id,
        }


@dataclass(frozen=True)
class MarketStatePrice:
    status: SectionStatus
    current: float | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "current": self.current,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TimeframeSwingSnapshot:
    """Per-timeframe structure snapshot for MarketState.

    ``swing_highs`` / ``swing_lows`` remain price projections for compatibility.
    ``swings`` is the authoritative event list (id, kind, index, times).
    """

    timeframe: str
    swing_highs: tuple[float, ...]
    swing_lows: tuple[float, ...]
    trend: str
    reason: str
    swings: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "swing_highs": list(self.swing_highs),
            "swing_lows": list(self.swing_lows),
            "trend": self.trend,
            "reason": self.reason,
            "swings": list(self.swings),
        }


@dataclass(frozen=True)
class MultiTimeframeTrendSnapshot:
    score: int | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStateStructure:
    """Structure section of MarketState.

    ``structure_score`` is the configured categorical score from trend
    classification (aligned/ranging/unknown). It is **not** confidence,
    probability, or trend magnitude.
    """

    status: SectionStatus
    method_id: str | None
    trend: str | None
    structure_score: int | None
    reason: str | None
    entry_timeframe: TimeframeSwingSnapshot | None
    by_timeframe: tuple[TimeframeSwingSnapshot, ...]
    multi_timeframe: MultiTimeframeTrendSnapshot | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "method_id": self.method_id,
            "trend": self.trend,
            "structure_score": self.structure_score,
            "reason": self.reason,
            "entry_timeframe": (
                self.entry_timeframe.to_dict() if self.entry_timeframe else None
            ),
            "by_timeframe": [item.to_dict() for item in self.by_timeframe],
            "multi_timeframe": (
                self.multi_timeframe.to_dict() if self.multi_timeframe else None
            ),
        }


@dataclass(frozen=True)
class MarketStateMomentum:
    status: SectionStatus
    method_id: str | None
    direction: str | None
    strength: float | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "method_id": self.method_id,
            "direction": self.direction,
            "strength": self.strength,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStatePhase:
    status: SectionStatus
    method_id: str | None
    phase: str | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "method_id": self.method_id,
            "phase": self.phase,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStateIndicators:
    status: SectionStatus
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    relative_volume: float | None
    ema_fast: float | None
    ema_slow: float | None
    atr: float | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "rsi": self.rsi,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "relative_volume": self.relative_volume,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "atr": self.atr,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStateVolatility:
    status: SectionStatus
    method_id: str | None
    range_expansion_state: str | None
    range_expansion_ratio: float | None
    atr: float | None
    reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "method_id": self.method_id,
            "range_expansion_state": self.range_expansion_state,
            "range_expansion_ratio": self.range_expansion_ratio,
            "atr": self.atr,
            "reason": self.reason,
        }


def _zone_to_dict(zone: Zone) -> dict[str, Any]:
    """Serialize a Zone for MarketState; preserves provenance via Zone.to_dict."""
    return zone.to_dict()


@dataclass(frozen=True)
class NearestZoneSnapshot:
    zone_id: int
    name: str
    timeframe: str
    strength: int
    side: str
    distance_price: float
    distance_pips: float
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "timeframe": self.timeframe,
            "strength": self.strength,
            "side": self.side,
            "distance_price": self.distance_price,
            "distance_pips": self.distance_pips,
            "source": self.source,
        }


@dataclass(frozen=True)
class MarketStateZones:
    status: SectionStatus
    active_zones: tuple[dict[str, Any], ...]
    nearest: NearestZoneSnapshot | None
    inside_zone: bool | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "active_zones": list(self.active_zones),
            "nearest": self.nearest.to_dict() if self.nearest else None,
            "inside_zone": self.inside_zone,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStateSession:
    status: SectionStatus
    session: str | None
    active_sessions: tuple[str, ...]
    overlap: bool | None
    high_liquidity: bool | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "session": self.session,
            "active_sessions": list(self.active_sessions),
            "overlap": self.overlap,
            "high_liquidity": self.high_liquidity,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketStateLiquidity:
    status: SectionStatus
    method_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "method_id": self.method_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MarketState:
    """Deterministic, versioned AI-facing snapshot derived from FeatureContext."""

    metadata: MarketStateMetadata
    price: MarketStatePrice
    structure: MarketStateStructure
    momentum: MarketStateMomentum
    phase: MarketStatePhase
    indicators: MarketStateIndicators
    volatility: MarketStateVolatility
    zones: MarketStateZones
    session: MarketStateSession
    liquidity: MarketStateLiquidity

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "price": self.price.to_dict(),
            "structure": self.structure.to_dict(),
            "momentum": self.momentum.to_dict(),
            "phase": self.phase.to_dict(),
            "indicators": self.indicators.to_dict(),
            "volatility": self.volatility.to_dict(),
            "zones": self.zones.to_dict(),
            "session": self.session.to_dict(),
            "liquidity": self.liquidity.to_dict(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
