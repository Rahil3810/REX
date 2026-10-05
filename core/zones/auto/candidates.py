"""Replaceable automatic zone candidate generators."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.features.generators.bos import detect_swing_bos_series
from core.features.generators.swings import SwingEvent, SwingKind
from core.zones.auto.atr import causal_atr
from core.zones.auto.config import SwingClusterZoneConfig
from core.zones.auto.evidence import (
    AutomaticZone,
    ZoneEvidence,
    ZoneLifecycleStatus,
)
from models.bar import Bar
from models.zone import Zone, ZoneKind, ZoneSource


@dataclass(frozen=True)
class ZoneCluster:
    """Intermediate price cluster before Zone materialization."""

    kind: ZoneKind
    swings: tuple[SwingEvent, ...]
    low: float
    high: float
    tolerance: float
    atr_used: float | None


class ZoneCandidateGenerator(Protocol):
    """Pluggable candidate generator (V1 swing-cluster; future KDE, etc.)."""

    method_id: str

    def generate_candidates(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingEvent],
        *,
        timeframe: str,
        asof_index: int,
        asof_time: datetime,
    ) -> tuple[AutomaticZone, ...]:
        """Produce automatic zones using only information available at asof."""
        ...


def ranking_strength_v1(
    *,
    contributing_swing_count: int,
    touch_count: int,
    status: ZoneLifecycleStatus,
) -> int:
    """Transparent 0–10 ranking heuristic — NOT confidence or probability.

    ``min(10, contributing_swings + touch_count // 2)``, then:
    - broken → floor at most 2 (still identifiable, deprioritized)
    - tested → unchanged
    - fresh → unchanged
    """
    raw = min(10, max(0, contributing_swing_count + touch_count // 2))
    if status is ZoneLifecycleStatus.BROKEN:
        return min(raw, 2)
    return raw


def deterministic_zone_id(
    *,
    timeframe: str,
    kind: ZoneKind,
    low: float,
    high: float,
    origin_swing_id: str,
) -> int:
    """Stable positive integer id from cluster identity (not a UUID)."""
    key = f"{timeframe}|{kind.value}|{low:.10f}|{high:.10f}|{origin_swing_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 1_000_000_000 + 1


class SwingClusterZoneGeneratorV1:
    """Cluster nearby confirmed swing prices into supply/demand bands."""

    def __init__(self, config: SwingClusterZoneConfig | None = None) -> None:
        self.config = config or SwingClusterZoneConfig()

    @property
    def method_id(self) -> str:
        return self.config.method_id

    def generate_candidates(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingEvent],
        *,
        timeframe: str,
        asof_index: int,
        asof_time: datetime,
    ) -> tuple[AutomaticZone, ...]:
        if not bars or asof_index < 0 or asof_index >= len(bars):
            return ()

        available = tuple(
            swing
            for swing in swings
            if swing.confirmation_index <= asof_index
            and swing.confirmation_time <= asof_time
        )
        if not available:
            return ()

        atr = causal_atr(
            bars, asof_index=asof_index, period=self.config.atr_period
        )
        tolerance = (
            self.config.cluster_atr_multiple * atr
            if atr is not None
            else self.config.absolute_price_tolerance
        )
        half_width = (
            self.config.single_swing_half_width_atr_multiple * atr
            if atr is not None
            else self.config.single_swing_half_width_absolute
        )

        clusters: list[ZoneCluster] = []
        clusters.extend(
            self._cluster_kind(
                available,
                swing_kind=SwingKind.HIGH,
                zone_kind=ZoneKind.SUPPLY,
                tolerance=tolerance,
                half_width=half_width,
                atr_used=atr,
            )
        )
        clusters.extend(
            self._cluster_kind(
                available,
                swing_kind=SwingKind.LOW,
                zone_kind=ZoneKind.DEMAND,
                tolerance=tolerance,
                half_width=half_width,
                atr_used=atr,
            )
        )

        bos_broken_ids = {
            event.broken_swing.id
            for event in detect_swing_bos_series(bars[: asof_index + 1], available)
        }

        results: list[AutomaticZone] = []
        for cluster in clusters:
            if len(cluster.swings) < self.config.min_contributing_swings:
                continue
            results.append(
                self._materialize(
                    bars=bars,
                    cluster=cluster,
                    timeframe=timeframe,
                    asof_index=asof_index,
                    asof_time=asof_time,
                    bos_broken_ids=bos_broken_ids,
                )
            )

        results.sort(
            key=lambda item: (
                item.zone.kind.value if item.zone.kind else "",
                item.zone.low,
                item.zone.high,
                item.zone.id,
            )
        )
        return tuple(results)

    def _cluster_kind(
        self,
        swings: Sequence[SwingEvent],
        *,
        swing_kind: SwingKind,
        zone_kind: ZoneKind,
        tolerance: float,
        half_width: float,
        atr_used: float | None,
    ) -> list[ZoneCluster]:
        selected = sorted(
            (swing for swing in swings if swing.kind is swing_kind),
            key=lambda swing: (swing.price, swing.index, swing.id),
        )
        if not selected:
            return []

        clusters: list[ZoneCluster] = []
        current: list[SwingEvent] = [selected[0]]
        for swing in selected[1:]:
            cluster_high = max(item.price for item in current)
            # Merge if within tolerance of the existing cluster high edge.
            if swing.price - cluster_high <= tolerance:
                current.append(swing)
                continue
            clusters.append(
                self._close_cluster(
                    current,
                    zone_kind=zone_kind,
                    half_width=half_width,
                    tolerance=tolerance,
                    atr_used=atr_used,
                )
            )
            current = [swing]
        clusters.append(
            self._close_cluster(
                current,
                zone_kind=zone_kind,
                half_width=half_width,
                tolerance=tolerance,
                atr_used=atr_used,
            )
        )
        return clusters

    @staticmethod
    def _close_cluster(
        swings: list[SwingEvent],
        *,
        zone_kind: ZoneKind,
        half_width: float,
        tolerance: float,
        atr_used: float | None,
    ) -> ZoneCluster:
        prices = [swing.price for swing in swings]
        low = min(prices)
        high = max(prices)
        if low == high:
            low = low - half_width
            high = high + half_width
        if low >= high:
            # Degenerate half_width — expand by a tiny epsilon from mid.
            mid = (low + high) / 2.0 if low == high else low
            low = mid - max(half_width, 1e-12)
            high = mid + max(half_width, 1e-12)
        # Origin = earliest confirmed swing in the cluster.
        ordered = tuple(
            sorted(swings, key=lambda swing: (swing.confirmation_index, swing.index, swing.id))
        )
        return ZoneCluster(
            kind=zone_kind,
            swings=ordered,
            low=low,
            high=high,
            tolerance=tolerance,
            atr_used=atr_used,
        )

    def _materialize(
        self,
        *,
        bars: Sequence[Bar],
        cluster: ZoneCluster,
        timeframe: str,
        asof_index: int,
        asof_time: datetime,
        bos_broken_ids: set[str],
    ) -> AutomaticZone:
        origin = cluster.swings[0]
        lifecycle = _evaluate_lifecycle(
            bars=bars,
            low=cluster.low,
            high=cluster.high,
            kind=cluster.kind,
            start_index=origin.confirmation_index,
            asof_index=asof_index,
            departure_lookback=self.config.departure_lookback_bars,
        )
        strength = ranking_strength_v1(
            contributing_swing_count=len(cluster.swings),
            touch_count=lifecycle.touch_count,
            status=lifecycle.status,
        )
        zone_id = deterministic_zone_id(
            timeframe=timeframe,
            kind=cluster.kind,
            low=cluster.low,
            high=cluster.high,
            origin_swing_id=origin.id,
        )
        name = (
            f"auto_{cluster.kind.value}_{timeframe}_"
            f"{origin.index}_{len(cluster.swings)}"
        )
        zone = Zone(
            id=zone_id,
            name=name,
            low=cluster.low,
            high=cluster.high,
            timeframe=timeframe,
            strength=strength,
            kind=cluster.kind,
            source=ZoneSource.AUTOMATIC,
        )
        contributing_ids = tuple(swing.id for swing in cluster.swings)
        evidence = ZoneEvidence(
            method_id=self.method_id,
            origin_swing_id=origin.id,
            origin_index=origin.index,
            origin_timestamp=origin.timestamp,
            origin_confirmation_index=origin.confirmation_index,
            origin_confirmation_time=origin.confirmation_time,
            contributing_swing_ids=contributing_ids,
            contributing_swing_count=len(contributing_ids),
            touch_count=lifecycle.touch_count,
            mitigation_count=lifecycle.mitigation_count,
            status=lifecycle.status,
            zone_age_bars=max(0, asof_index - origin.confirmation_index),
            departure_move=lifecycle.departure_move,
            reaction_magnitude=lifecycle.reaction_magnitude,
            bos_associated=any(swing_id in bos_broken_ids for swing_id in contributing_ids),
            atr_used=cluster.atr_used,
            cluster_tolerance=cluster.tolerance,
            asof_index=asof_index,
            asof_time=asof_time,
        )
        return AutomaticZone(zone=zone, evidence=evidence)


@dataclass(frozen=True)
class _LifecycleStats:
    touch_count: int
    mitigation_count: int
    status: ZoneLifecycleStatus
    departure_move: float | None
    reaction_magnitude: float | None


def _evaluate_lifecycle(
    *,
    bars: Sequence[Bar],
    low: float,
    high: float,
    kind: ZoneKind,
    start_index: int,
    asof_index: int,
    departure_lookback: int,
) -> _LifecycleStats:
    """Causal lifecycle using close semantics for mitigation/break; wick for touches.

    Broken:
      SUPPLY — close strictly above ``high``
      DEMAND — close strictly below ``low``
    Wick-only penetration does not break the zone.

    Touch: bar range overlaps the band (wick allowed) before break.
    Mitigation: close inside the band before break.
    """
    touch_count = 0
    mitigation_count = 0
    broken = False
    break_index: int | None = None

    for index in range(max(0, start_index), asof_index + 1):
        bar = bars[index]
        overlaps = bar.high >= low and bar.low <= high
        close_inside = low <= bar.close <= high
        if kind is ZoneKind.SUPPLY:
            is_break = bar.close > high
        else:
            is_break = bar.close < low

        if is_break:
            broken = True
            break_index = index
            break

        if overlaps:
            touch_count += 1
        if close_inside:
            mitigation_count += 1

    if broken:
        status = ZoneLifecycleStatus.BROKEN
    elif mitigation_count > 0:
        status = ZoneLifecycleStatus.TESTED
    else:
        status = ZoneLifecycleStatus.FRESH

    departure_move: float | None = None
    reaction_magnitude: float | None = None
    end = min(asof_index, start_index + departure_lookback)
    if end > start_index:
        origin_mid = (low + high) / 2.0
        moves: list[float] = []
        reactions: list[float] = []
        for index in range(start_index + 1, end + 1):
            if break_index is not None and index > break_index:
                break
            bar = bars[index]
            if kind is ZoneKind.SUPPLY:
                # Departure = move down away from supply after origin.
                moves.append(origin_mid - bar.close)
                if bar.close < low:
                    reactions.append(low - bar.close)
            else:
                moves.append(bar.close - origin_mid)
                if bar.close > high:
                    reactions.append(bar.close - high)
        if moves:
            departure_move = max(0.0, max(moves))
        if reactions:
            reaction_magnitude = max(reactions)

    return _LifecycleStats(
        touch_count=touch_count,
        mitigation_count=mitigation_count,
        status=status,
        departure_move=departure_move,
        reaction_magnitude=reaction_magnitude,
    )
