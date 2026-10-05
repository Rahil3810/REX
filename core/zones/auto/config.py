"""Automatic Zone Generation V1 configuration."""

from __future__ import annotations

from dataclasses import dataclass


METHOD_SWING_CLUSTER_ZONE_V1 = "swing_cluster_zone_v1"


@dataclass(frozen=True)
class SwingClusterZoneConfig:
    """Parameters for swing-cluster automatic zone candidate generation.

    Clustering tolerance is ATR-relative when a causal ATR is available:

        |price_a - price_b| <= cluster_atr_multiple * atr

    If ATR cannot be computed (insufficient bars), ``absolute_price_tolerance``
    is used instead. Neither value is a magic undocumented percentage of price.
    """

    atr_period: int = 14
    cluster_atr_multiple: float = 0.35
    absolute_price_tolerance: float = 0.0005
    """Fallback merge distance when ATR is unavailable (price units)."""

    single_swing_half_width_atr_multiple: float = 0.10
    """Expand a single-swing cluster into a band: half-width = multiple * ATR."""

    single_swing_half_width_absolute: float = 0.0002
    """Fallback half-width when ATR is unavailable."""

    min_contributing_swings: int = 1
    departure_lookback_bars: int = 5
    method_id: str = METHOD_SWING_CLUSTER_ZONE_V1
