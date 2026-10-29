"""MA Confluence Zone Generator V1 (research, causal, frozen snapshots).

Hypothesis
----------
When EMA20 and EMA50 converge within a fraction of ATR14 for a sustained
number of bars, the MA cluster may define a meaningful price-interest band.

EMA200 is recorded as evidence only — not a confluence gate.

Lifecycle
---------
- Create when convergence persists for ``min_persist`` bars; freeze low/high.
- Do not move bounds while active.
- Expire after ``exit_persist`` bars with separation > ``k_exit * ATR``.
- Retain all completed historical snapshots (no retention cap).
- At most one *current* active cluster; a new confluence after expire gets a
  new zone id.

ATR source: ``IndicatorEngine.atr`` (same causal prefix as EMAs).
Not comparable to swing-zone ``causal_atr`` without reconciliation.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import pandas as pd

from core.indicators import IndicatorEngine, PandasTAProvider
from core.zones.auto.generated import GeneratedZone
from models.bar import Bar
from models.zone import Zone, ZoneSource

METHOD_MA_CONFLUENCE_ZONE_V1 = "ma_confluence_zone_v1"
GENERATOR_VERSION = "ma_confluence_zone_v1.0.0"


class MAConfluenceStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


@dataclass(frozen=True)
class MAConfluenceZoneConfig:
    """Fixed research parameters for the first validation batch."""

    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    atr_period: int = 14
    k_enter: float = 0.30
    k_exit: float = 0.60
    min_persist: int = 3
    exit_persist: int = 3
    min_width_atr: float = 0.25
    method_id: str = METHOD_MA_CONFLUENCE_ZONE_V1
    generator_version: str = GENERATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "ema_trend": self.ema_trend,
            "atr_period": self.atr_period,
            "k_enter": self.k_enter,
            "k_exit": self.k_exit,
            "min_persist": self.min_persist,
            "exit_persist": self.exit_persist,
            "min_width_atr": self.min_width_atr,
            "method_id": self.method_id,
            "generator_version": self.generator_version,
            "ema200_role": "evidence_only",
            "note": (
                "First validation batch — do not retune on the same labels."
            ),
        }


@dataclass(frozen=True)
class MAConfluenceEvidence:
    """Creation-time + lifecycle evidence for an MA confluence zone."""

    method_id: str
    generator_version: str
    timeframe: str
    symbol: str
    created_index: int
    created_time: datetime
    convergence_start_index: int
    convergence_start_time: datetime
    convergence_duration_bars: int
    ema20: float
    ema50: float
    ema200: float | None
    atr14: float
    separation: float
    separation_over_atr: float
    status: MAConfluenceStatus
    expired_index: int | None
    expired_time: datetime | None
    asof_index: int
    asof_time: datetime
    k_enter: float
    k_exit: float
    min_persist: int
    exit_persist: int
    min_width_atr: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "generator_version": self.generator_version,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "created_index": self.created_index,
            "created_time": self.created_time.isoformat(sep=" "),
            "convergence_start_index": self.convergence_start_index,
            "convergence_start_time": self.convergence_start_time.isoformat(
                sep=" "
            ),
            "convergence_duration_bars": self.convergence_duration_bars,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "ema200": self.ema200,
            "atr14": self.atr14,
            "separation": self.separation,
            "separation_over_atr": self.separation_over_atr,
            "status": self.status.value,
            "expired_index": self.expired_index,
            "expired_time": (
                None
                if self.expired_time is None
                else self.expired_time.isoformat(sep=" ")
            ),
            "asof_index": self.asof_index,
            "asof_time": self.asof_time.isoformat(sep=" "),
            "k_enter": self.k_enter,
            "k_exit": self.k_exit,
            "min_persist": self.min_persist,
            "exit_persist": self.exit_persist,
            "min_width_atr": self.min_width_atr,
        }


def compute_zone_bounds(
    ema_fast: float,
    ema_slow: float,
    atr: float,
    *,
    min_width_atr: float,
) -> tuple[float, float]:
    """ATR-padded MA cluster: min/max EMAs with width floor."""
    cluster_low = min(ema_fast, ema_slow)
    cluster_high = max(ema_fast, ema_slow)
    width = cluster_high - cluster_low
    floor = min_width_atr * atr
    if width < floor:
        mid = (cluster_low + cluster_high) / 2.0
        half = floor / 2.0
        return mid - half, mid + half
    return cluster_low, cluster_high


def deterministic_ma_zone_id(
    *,
    timeframe: str,
    created_index: int,
    low: float,
    high: float,
    method_id: str = METHOD_MA_CONFLUENCE_ZONE_V1,
) -> int:
    """Stable positive integer id from confluence creation identity."""
    key = f"{method_id}|{timeframe}|{created_index}|{low:.10f}|{high:.10f}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 1_000_000_000 + 1


@dataclass
class _ActiveCluster:
    zone_id: int
    low: float
    high: float
    created_index: int
    created_time: datetime
    convergence_start_index: int
    convergence_start_time: datetime
    ema20: float
    ema50: float
    ema200: float | None
    atr14: float
    separation: float
    separation_over_atr: float
    diverge_streak: int = 0


class MAConfluenceZoneGenerator:
    """Causal MA confluence zone discovery with frozen historical snapshots."""

    def __init__(
        self,
        config: MAConfluenceZoneConfig | None = None,
        *,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        self.config = config or MAConfluenceZoneConfig()
        self._engine = indicator_engine or IndicatorEngine(PandasTAProvider())

    @property
    def method_id(self) -> str:
        return self.config.method_id

    def generate(
        self,
        bars: Sequence[Bar],
        *,
        timeframe: str,
        asof_index: int,
        asof_time: datetime | None = None,
    ) -> tuple[GeneratedZone, ...]:
        if not bars or asof_index < 0 or asof_index >= len(bars):
            return ()

        prefix = list(bars[: asof_index + 1])
        resolved_asof = asof_time or prefix[-1].timestamp
        if prefix[-1].timestamp > resolved_asof:
            # Strict causality: drop bars after asof_time if provided.
            prefix = [b for b in prefix if b.timestamp <= resolved_asof]
            if not prefix:
                return ()
            asof_index = len(prefix) - 1

        symbol = prefix[0].symbol
        series = self._indicator_series(prefix)
        if series is None:
            return ()

        ema_fast_s, ema_slow_s, ema_trend_s, atr_s = series
        cfg = self.config
        completed: list[GeneratedZone] = []
        active: _ActiveCluster | None = None
        converge_streak = 0
        converge_start_index: int | None = None

        for index in range(len(prefix)):
            ema_f = _finite(ema_fast_s.iloc[index])
            ema_s = _finite(ema_slow_s.iloc[index])
            atr_v = _finite(atr_s.iloc[index])
            ema_t = _finite(ema_trend_s.iloc[index])
            bar = prefix[index]

            if ema_f is None or ema_s is None or atr_v is None or atr_v <= 0:
                converge_streak = 0
                converge_start_index = None
                if active is not None:
                    # Missing indicators while active: count as divergence.
                    active.diverge_streak += 1
                    if active.diverge_streak >= cfg.exit_persist:
                        completed.append(
                            self._materialize(
                                active,
                                timeframe=timeframe,
                                symbol=symbol,
                                status=MAConfluenceStatus.EXPIRED,
                                expired_index=index,
                                expired_time=bar.timestamp,
                                asof_index=asof_index,
                                asof_time=resolved_asof,
                                convergence_duration_bars=(
                                    index - active.convergence_start_index
                                ),
                            )
                        )
                        active = None
                continue

            sep = abs(ema_f - ema_s)
            sep_atr = sep / atr_v
            converging = sep_atr <= cfg.k_enter
            diverging = sep_atr > cfg.k_exit

            if converging:
                if converge_streak == 0:
                    converge_start_index = index
                converge_streak += 1
            else:
                converge_streak = 0
                converge_start_index = None

            if active is None:
                if (
                    converging
                    and converge_streak >= cfg.min_persist
                    and converge_start_index is not None
                ):
                    low, high = compute_zone_bounds(
                        ema_f,
                        ema_s,
                        atr_v,
                        min_width_atr=cfg.min_width_atr,
                    )
                    zone_id = deterministic_ma_zone_id(
                        timeframe=timeframe,
                        created_index=index,
                        low=low,
                        high=high,
                        method_id=cfg.method_id,
                    )
                    duration = index - converge_start_index + 1
                    active = _ActiveCluster(
                        zone_id=zone_id,
                        low=low,
                        high=high,
                        created_index=index,
                        created_time=bar.timestamp,
                        convergence_start_index=converge_start_index,
                        convergence_start_time=prefix[
                            converge_start_index
                        ].timestamp,
                        ema20=ema_f,
                        ema50=ema_s,
                        ema200=ema_t,
                        atr14=atr_v,
                        separation=sep,
                        separation_over_atr=sep_atr,
                    )
                    # duration recorded at materialize; store via created state
                    _ = duration
                continue

            # Active cluster — bounds frozen; watch for expire.
            if diverging:
                active.diverge_streak += 1
            else:
                active.diverge_streak = 0

            if active.diverge_streak >= cfg.exit_persist:
                completed.append(
                    self._materialize(
                        active,
                        timeframe=timeframe,
                        symbol=symbol,
                        status=MAConfluenceStatus.EXPIRED,
                        expired_index=index,
                        expired_time=bar.timestamp,
                        asof_index=asof_index,
                        asof_time=resolved_asof,
                        convergence_duration_bars=(
                            active.created_index
                            - active.convergence_start_index
                            + 1
                        ),
                    )
                )
                active = None
                # Allow a new confluence to start counting on subsequent bars.
                if converging:
                    converge_streak = 1
                    converge_start_index = index
                else:
                    converge_streak = 0
                    converge_start_index = None

        results = list(completed)
        if active is not None:
            results.append(
                self._materialize(
                    active,
                    timeframe=timeframe,
                    symbol=symbol,
                    status=MAConfluenceStatus.ACTIVE,
                    expired_index=None,
                    expired_time=None,
                    asof_index=asof_index,
                    asof_time=resolved_asof,
                    convergence_duration_bars=(
                        active.created_index
                        - active.convergence_start_index
                        + 1
                    ),
                )
            )

        results.sort(
            key=lambda item: (
                item.evidence.created_index,
                item.zone.low,
                item.zone.high,
                item.zone.id,
            )
        )
        return tuple(results)

    def _indicator_series(
        self, prefix: Sequence[Bar]
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series] | None:
        cfg = self.config
        # EMA200 is evidence-only; do not block generation on its warmup.
        min_bars = max(cfg.ema_slow, cfg.atr_period) + 1
        if len(prefix) < min_bars:
            return None
        try:
            ema_fast = self._engine.ema(prefix, length=cfg.ema_fast)
            ema_slow = self._engine.ema(prefix, length=cfg.ema_slow)
            atr = self._engine.atr(prefix, length=cfg.atr_period)
            if len(prefix) >= cfg.ema_trend + 1:
                ema_trend = self._engine.ema(prefix, length=cfg.ema_trend)
            else:
                ema_trend = pd.Series([float("nan")] * len(prefix))
        except Exception:
            return None
        if ema_fast.empty or ema_slow.empty or atr.empty:
            return None
        return ema_fast, ema_slow, ema_trend, atr

    def _materialize(
        self,
        active: _ActiveCluster,
        *,
        timeframe: str,
        symbol: str,
        status: MAConfluenceStatus,
        expired_index: int | None,
        expired_time: datetime | None,
        asof_index: int,
        asof_time: datetime,
        convergence_duration_bars: int,
    ) -> GeneratedZone:
        cfg = self.config
        name = (
            f"auto_ma_confluence_{timeframe}_"
            f"{active.created_index}_{status.value}"
        )
        zone = Zone(
            id=active.zone_id,
            name=name,
            low=active.low,
            high=active.high,
            timeframe=timeframe,
            strength=5,
            kind=None,
            source=ZoneSource.AUTOMATIC,
        )
        evidence = MAConfluenceEvidence(
            method_id=cfg.method_id,
            generator_version=cfg.generator_version,
            timeframe=timeframe,
            symbol=symbol,
            created_index=active.created_index,
            created_time=active.created_time,
            convergence_start_index=active.convergence_start_index,
            convergence_start_time=active.convergence_start_time,
            convergence_duration_bars=convergence_duration_bars,
            ema20=active.ema20,
            ema50=active.ema50,
            ema200=active.ema200,
            atr14=active.atr14,
            separation=active.separation,
            separation_over_atr=active.separation_over_atr,
            status=status,
            expired_index=expired_index,
            expired_time=expired_time,
            asof_index=asof_index,
            asof_time=asof_time,
            k_enter=cfg.k_enter,
            k_exit=cfg.k_exit,
            min_persist=cfg.min_persist,
            exit_persist=cfg.exit_persist,
            min_width_atr=cfg.min_width_atr,
        )
        return GeneratedZone(zone=zone, evidence=evidence)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
