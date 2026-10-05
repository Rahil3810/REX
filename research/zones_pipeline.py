"""Research-only: free OHLC → HTF → Automatic Zone V1 → Zone Evaluation V1.

Does not touch live trading, SignalEngine, or production HistoricalStorage.
Does not modify Automatic Zone V1 or Zone Evaluation V1 algorithms.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, Sequence

from core.features.config import SwingDetectionConfig
from core.features.generators.swings import SwingGenerator
from core.market import require_instrument
from core.zones import (
    METHOD_SWING_CLUSTER_ZONE_V1,
    METHOD_ZONE_EVAL_V1,
    AutomaticZone,
    AutomaticZoneGenerator,
    SwingClusterZoneConfig,
    ZoneEvaluation,
    ZoneEvaluationConfig,
    ZoneEvaluator,
)
from models.bar import Bar
from models.zone import ZoneKind
from research.free_ohlc.adapter import AdapterResult, load_free_ohlc
from research.free_ohlc.dataset import build_research_dataset
from research.free_ohlc.resampler import SUPPORTED_TIMEFRAMES
from research.structure_zone_experiment import run_structure_context_on_zones
from research.geometry_zone_experiment import run_geometry_lifecycle_on_zones

PIPELINE_VERSION = "research_zones_smoke_v4"
DEFAULT_TIMEFRAMES: tuple[str, ...] = ("M15", "H1")
DEFAULT_EVAL_TIMEFRAMES: tuple[str, ...] = ("M15", "H1", "H4", "D1")

CLASSIFICATION_INSUFFICIENT = "INSUFFICIENT_DATA"
CLASSIFICATION_STABLE = "V1_STABLE_ENOUGH_FOR_NEXT_EXPERIMENT"
CLASSIFICATION_DIAGNOSTIC = "V1_REQUIRES_DIAGNOSTIC_REVIEW"

# Stability / sufficiency thresholds (research heuristics, not trading gates).
MIN_M15_INTERACTIONS = 50
MIN_M15_ZONES = 10
MIN_H1_BARS_FOR_USABLE = 50
MIN_H1_INTERACTIONS_FOR_USABLE = 20
MAX_SEGMENT_RATE_SPREAD = 0.20  # success/broken rate range across thirds


@dataclass(frozen=True)
class DatasetBounds:
    """Observed free-OHLC M1 coverage after optional invalid-OHLC policy."""

    source_path: str
    symbol: str
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    first_date: date | None
    last_date: date | None
    accepted_m1_bars: int
    dropped_invalid_bars: int
    volume_type: str
    timezone_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "symbol": self.symbol,
            "first_timestamp": (
                None
                if self.first_timestamp is None
                else self.first_timestamp.isoformat(sep=" ")
            ),
            "last_timestamp": (
                None
                if self.last_timestamp is None
                else self.last_timestamp.isoformat(sep=" ")
            ),
            "first_date": None if self.first_date is None else self.first_date.isoformat(),
            "last_date": None if self.last_date is None else self.last_date.isoformat(),
            "accepted_m1_bars": self.accepted_m1_bars,
            "dropped_invalid_bars": self.dropped_invalid_bars,
            "volume_type": self.volume_type,
            "timezone_policy": self.timezone_policy,
        }


@dataclass(frozen=True)
class TimeframeZoneResearchResult:
    timeframe: str
    bar_count: int
    swing_count: int
    zones: tuple[AutomaticZone, ...]
    evaluations: tuple[ZoneEvaluation, ...]
    report: dict[str, Any]


@dataclass(frozen=True)
class ResearchZonesSmokeResult:
    source_path: str
    symbol: str
    requested_start: str | None
    requested_end: str | None
    effective_start: str | None
    effective_end: str | None
    dataset_bounds: DatasetBounds
    by_timeframe: dict[str, TimeframeZoneResearchResult]
    summary: dict[str, Any]
    provenance: dict[str, Any]
    segment_stability: dict[str, Any]
    structure_context_experiment: dict[str, Any] | None
    geometry_lifecycle_experiment: dict[str, Any] | None
    research_classification: str
    classification_rationale: str
    deterministic_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "dataset_bounds": self.dataset_bounds.to_dict(),
            "provenance": self.provenance,
            "timeframes": {
                tf: result.report for tf, result in self.by_timeframe.items()
            },
            "summary": self.summary,
            "segment_stability": self.segment_stability,
            "structure_context_experiment": self.structure_context_experiment,
            "geometry_lifecycle_experiment": self.geometry_lifecycle_experiment,
            "research_classification": self.research_classification,
            "classification_rationale": self.classification_rationale,
            "deterministic_hash": self.deterministic_hash,
            "disclaimer": (
                "Outcome rates under zone_eval_v1 are not predictive accuracy "
                "or zone accuracy."
            ),
        }


def discover_dataset_bounds(
    csv_path: Path | str,
    *,
    symbol: str = "EURUSD",
    skip_invalid_ohlc: bool = True,
    start: date | None = None,
    end: date | None = None,
) -> DatasetBounds:
    """Derive first/last timestamps from the free OHLC file (not hard-coded)."""
    path = Path(csv_path)
    adapter = load_free_ohlc(
        path,
        symbol=symbol,
        timeframe="M1",
        start=start,
        end=end,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )
    first = adapter.stats.first_timestamp
    last = adapter.stats.last_timestamp
    return DatasetBounds(
        source_path=str(path),
        symbol=symbol.strip().upper(),
        first_timestamp=first,
        last_timestamp=last,
        first_date=None if first is None else first.date(),
        last_date=None if last is None else last.date(),
        accepted_m1_bars=int(adapter.stats.rows_accepted),
        dropped_invalid_bars=int(adapter.stats.rows_dropped_invalid),
        volume_type=str(adapter.stats.volume_type),
        timezone_policy=str(adapter.stats.timezone_policy),
    )


def resolve_evaluation_window(
    csv_path: Path | str,
    *,
    symbol: str = "EURUSD",
    start: date | None = None,
    end: date | None = None,
    skip_invalid_ohlc: bool = True,
) -> tuple[DatasetBounds, date | None, date | None]:
    """Resolve CLI overrides against discovered dataset bounds."""
    bounds = discover_dataset_bounds(
        csv_path,
        symbol=symbol,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )
    if bounds.first_date is None or bounds.last_date is None:
        return bounds, start, end

    effective_start = start if start is not None else bounds.first_date
    effective_end = end if end is not None else bounds.last_date
    if effective_start > effective_end:
        raise ValueError(
            f"start {effective_start.isoformat()} is after end {effective_end.isoformat()}"
        )
    # Clamp overrides into observed coverage when both ends are known.
    if effective_start < bounds.first_date:
        effective_start = bounds.first_date
    if effective_end > bounds.last_date:
        effective_end = bounds.last_date
    return bounds, effective_start, effective_end


def split_date_range_into_thirds(
    start: date,
    end: date,
) -> tuple[tuple[str, date, date], ...]:
    """Split an inclusive calendar range into first/middle/final thirds."""
    if end < start:
        raise ValueError("end before start")
    days = (end - start).days + 1
    if days < 3:
        # Degenerate: emit one or more overlapping single-day windows.
        return (
            ("first_third", start, start),
            ("middle_third", start if days == 1 else end, start if days == 1 else end),
            ("final_third", end, end),
        )

    from datetime import timedelta

    third = days // 3
    mid = days - 2 * third
    a0 = start
    a1 = start + timedelta(days=third - 1)
    b0 = a1 + timedelta(days=1)
    b1 = b0 + timedelta(days=mid - 1)
    c0 = b1 + timedelta(days=1)
    c1 = end
    return (
        ("first_third", a0, a1),
        ("middle_third", b0, b1),
        ("final_third", c0, c1),
    )


def _safe_rate(num: int, den: int) -> float | None:
    return (num / den) if den else None


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
        }
    ordered = sorted(values)
    n = len(ordered)

    def _pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        idx = int(round((n - 1) * p))
        return ordered[max(0, min(n - 1, idx))]

    return {
        "count": n,
        "min": ordered[0],
        "max": ordered[-1],
        "mean": mean(ordered),
        "median": median(ordered),
        "p25": _pct(0.25),
        "p75": _pct(0.75),
    }


def _volume_stats(bars: Sequence[Bar], *, volume_type: str) -> dict[str, Any]:
    present = [float(b.volume) for b in bars if b.volume is not None]
    return {
        "volume_type": volume_type,
        "bars_with_volume": len(present),
        "bars_without_volume": sum(1 for b in bars if b.volume is None),
        "note": (
            "Preserved as tick_volume when present — not exchange volume; "
            "not used by Automatic Zone V1 generation."
        ),
        "distribution": _distribution(present),
    }


def _swing_count(bars: Sequence[Bar], *, timeframe: str, symbol: str) -> int:
    if not bars:
        return 0
    features = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
        {timeframe: list(bars)},
        require_instrument(symbol),
        entry_timeframe=timeframe,
        asof=bars[-1].timestamp,
    )
    return len(features.by_timeframe[timeframe].swings)


def _zone_detail(auto: AutomaticZone, evaluation: ZoneEvaluation | None) -> dict[str, Any]:
    zone = auto.zone
    ev = auto.evidence
    detail: dict[str, Any] = {
        "zone_id": zone.id,
        "name": zone.name,
        "kind": zone.kind.value if zone.kind is not None else None,
        "low": zone.low,
        "high": zone.high,
        "width": zone.high - zone.low,
        "timeframe": zone.timeframe,
        "strength": zone.strength,
        "source": zone.source.value if hasattr(zone.source, "value") else str(zone.source),
        "origin_swing_id": ev.origin_swing_id,
        "origin_index": ev.origin_index,
        "origin_timestamp": ev.origin_timestamp.isoformat(sep=" "),
        "origin_confirmation_index": ev.origin_confirmation_index,
        "origin_confirmation_time": ev.origin_confirmation_time.isoformat(sep=" "),
        "touch_count": ev.touch_count,
        "mitigation_count": ev.mitigation_count,
        "lifecycle_status": ev.status.value if hasattr(ev.status, "value") else str(ev.status),
        "contributing_swing_count": ev.contributing_swing_count,
        "zone_age_bars": ev.zone_age_bars,
        "asof_index": ev.asof_index,
        "asof_time": ev.asof_time.isoformat(sep=" "),
        "method_id": ev.method_id,
    }
    if evaluation is not None:
        detail["evaluation"] = {
            "interaction_count": evaluation.sample_count,
            "success_count": evaluation.successful_reaction_count,
            "failure_count": evaluation.failed_reaction_count,
            "broken_count": evaluation.broken_count,
            "unavailable_count": evaluation.unavailable_count,
            "success_rate": evaluation.success_rate,
            "median_mfe": evaluation.median_mfe,
            "median_mae": evaluation.median_mae,
            "average_mfe": evaluation.average_max_favorable_excursion,
            "average_mae": evaluation.average_max_adverse_excursion,
            "method_id": evaluation.method_id,
            "config": evaluation.config.to_dict(),
        }
    else:
        detail["evaluation"] = None
    return detail


def _outcome_counts(
    evaluations: Sequence[ZoneEvaluation],
) -> dict[str, Any]:
    success = sum(e.successful_reaction_count for e in evaluations)
    failure = sum(e.failed_reaction_count for e in evaluations)
    broken = sum(e.broken_count for e in evaluations)
    unavailable = sum(e.unavailable_count for e in evaluations)
    interactions = sum(e.sample_count for e in evaluations)
    decisive = success + failure + broken
    return {
        "interaction_count": interactions,
        "SUCCESS_count": success,
        "FAILURE_count": failure,
        "BROKEN_count": broken,
        "UNAVAILABLE_count": unavailable,
        "success_rate": _safe_rate(success, decisive),
        "failure_rate": _safe_rate(failure, decisive),
        "broken_rate": _safe_rate(broken, decisive),
        "unavailable_rate": _safe_rate(unavailable, interactions),
    }


def _compact_tf_metrics(
    *,
    bar_count: int,
    swing_count: int,
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
) -> dict[str, Any]:
    outcomes = _outcome_counts(evaluations)
    widths = [z.zone.high - z.zone.low for z in zones]
    strengths = [float(z.zone.strength) for z in zones]
    touches = [float(z.evidence.touch_count) for z in zones]
    interaction_per_zone = [float(e.sample_count) for e in evaluations]
    mfes = [e.median_mfe for e in evaluations if e.median_mfe is not None]
    maes = [e.median_mae for e in evaluations if e.median_mae is not None]
    zero_ix = sum(1 for e in evaluations if e.sample_count == 0)
    multi_ix = sum(1 for e in evaluations if e.sample_count > 1)
    return {
        "bar_count": bar_count,
        "swing_count": swing_count,
        "zone_count": len(zones),
        "supply_count": sum(1 for z in zones if z.zone.kind == ZoneKind.SUPPLY),
        "demand_count": sum(1 for z in zones if z.zone.kind == ZoneKind.DEMAND),
        **outcomes,
        "zone_generation_rate_per_bar": (
            (len(zones) / bar_count) if bar_count else None
        ),
        "interactions_per_zone": (
            (outcomes["interaction_count"] / len(zones)) if zones else None
        ),
        "zones_with_zero_interactions": zero_ix,
        "zones_with_multiple_interactions": multi_ix,
        "average_touches": mean(touches) if touches else None,
        "median_touches": median(touches) if touches else None,
        "average_zone_width": mean(widths) if widths else None,
        "median_zone_width": median(widths) if widths else None,
        "average_strength": mean(strengths) if strengths else None,
        "median_strength": median(strengths) if strengths else None,
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
        "mean_interactions_per_zone": mean(interaction_per_zone) if interaction_per_zone else None,
    }


def _timeframe_report(
    *,
    timeframe: str,
    bars: Sequence[Bar],
    swing_count: int,
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    source_path: str,
    symbol: str,
    dataset_provenance: Mapping[str, Any],
    adapter_stats: Mapping[str, Any],
    volume_type: str,
    dataset_start: str | None,
    dataset_end: str | None,
    resample_stats: Mapping[str, Any] | None,
) -> dict[str, Any]:
    eval_by_id = {e.zone_id: e for e in evaluations}
    outcomes = _outcome_counts(evaluations)
    widths = [z.zone.high - z.zone.low for z in zones]
    strengths = [float(z.zone.strength) for z in zones]
    touches = [float(z.evidence.touch_count) for z in zones]
    mfes_all = [
        float(ix.mfe)
        for e in evaluations
        for ix in e.interactions
        if ix.mfe is not None
    ]
    maes_all = [
        float(ix.mae)
        for e in evaluations
        for ix in e.interactions
        if ix.mae is not None
    ]
    zone_median_mfes = [e.median_mfe for e in evaluations if e.median_mfe is not None]
    zone_median_maes = [e.median_mae for e in evaluations if e.median_mae is not None]
    zero_ix = sum(1 for e in evaluations if e.sample_count == 0)
    multi_ix = sum(1 for e in evaluations if e.sample_count > 1)
    compact = _compact_tf_metrics(
        bar_count=len(bars),
        swing_count=swing_count,
        zones=zones,
        evaluations=evaluations,
    )

    return {
        "source_dataset": source_path,
        "symbol": symbol,
        "timeframe": timeframe,
        "dataset_start": dataset_start,
        "dataset_end": dataset_end,
        "accepted_m1_bars": adapter_stats.get("rows_accepted"),
        "dropped_invalid_bars": adapter_stats.get("rows_dropped_invalid"),
        "resampled_bar_count": len(bars),
        "incomplete_bucket_count": (
            None
            if resample_stats is None
            else resample_stats.get("skipped_incomplete_buckets")
        ),
        "bar_count": len(bars),
        "first_timestamp": bars[0].timestamp.isoformat(sep=" ") if bars else None,
        "last_timestamp": bars[-1].timestamp.isoformat(sep=" ") if bars else None,
        "swing_count": swing_count,
        "automatic_zone_count": len(zones),
        "zone_count": len(zones),
        "supply_count": compact["supply_count"],
        "demand_count": compact["demand_count"],
        "zone_ids": [z.zone.id for z in zones],
        "zones": [_zone_detail(z, eval_by_id.get(z.zone.id)) for z in zones],
        "evaluation_interaction_count": outcomes["interaction_count"],
        "interaction_count": outcomes["interaction_count"],
        "SUCCESS_count": outcomes["SUCCESS_count"],
        "FAILURE_count": outcomes["FAILURE_count"],
        "BROKEN_count": outcomes["BROKEN_count"],
        "UNAVAILABLE_count": outcomes["UNAVAILABLE_count"],
        "success_rate": outcomes["success_rate"],
        "failure_rate": outcomes["failure_rate"],
        "broken_rate": outcomes["broken_rate"],
        "unavailable_rate": outcomes["unavailable_rate"],
        "zone_generation_rate_per_bar": compact["zone_generation_rate_per_bar"],
        "interactions_per_zone": compact["interactions_per_zone"],
        "zones_with_zero_interactions": zero_ix,
        "zones_with_multiple_interactions": multi_ix,
        "average_touches": compact["average_touches"],
        "median_touches": compact["median_touches"],
        "zone_width_distribution": _distribution(widths),
        "zone_strength_distribution": _distribution(strengths),
        "touch_distribution": _distribution(touches),
        "mfe_statistics": {
            "interaction_mfe": _distribution(mfes_all),
            "median_of_zone_median_mfe": (
                median(zone_median_mfes) if zone_median_mfes else None
            ),
            "note": "MFE under zone_eval_v1 — not predictive accuracy.",
        },
        "mae_statistics": {
            "interaction_mae": _distribution(maes_all),
            "median_of_zone_median_mae": (
                median(zone_median_maes) if zone_median_maes else None
            ),
            "note": "MAE under zone_eval_v1 — not predictive accuracy.",
        },
        "mfe_mae_aggregates": {
            "median_of_zone_median_mfe": (
                median(zone_median_mfes) if zone_median_mfes else None
            ),
            "median_of_zone_median_mae": (
                median(zone_median_maes) if zone_median_maes else None
            ),
            "note": (
                "Outcome evaluation under zone_eval_v1 — not predictive accuracy."
            ),
        },
        "volume": _volume_stats(bars, volume_type=volume_type),
        "evaluation_configuration": (
            evaluations[0].config.to_dict() if evaluations else ZoneEvaluationConfig().to_dict()
        ),
        "research_summary": {
            "zones_generated": len(zones),
            "zones_evaluated": len(evaluations),
            "success_rate": outcomes["success_rate"],
            "failure_rate": outcomes["failure_rate"],
            "broken_rate": outcomes["broken_rate"],
            "unavailable_rate": outcomes["unavailable_rate"],
            "average_touches": compact["average_touches"],
            "median_touches": compact["median_touches"],
            "average_zone_width": compact["average_zone_width"],
            "average_strength": compact["average_strength"],
            "median_mfe": compact["median_mfe"],
            "median_mae": compact["median_mae"],
        },
        "resample_stats": dict(resample_stats) if resample_stats else None,
        "provenance": {
            "zone_method_id": METHOD_SWING_CLUSTER_ZONE_V1,
            "evaluation_method_id": METHOD_ZONE_EVAL_V1,
            "dataset": dict(dataset_provenance),
            "pipeline_version": PIPELINE_VERSION,
        },
    }


def run_timeframe_pipeline(
    bars: Sequence[Bar],
    *,
    timeframe: str,
    symbol: str,
    asof_index: int | None = None,
    swing_config: SwingDetectionConfig | None = None,
    cluster_config: SwingClusterZoneConfig | None = None,
    eval_config: ZoneEvaluationConfig | None = None,
) -> tuple[tuple[AutomaticZone, ...], tuple[ZoneEvaluation, ...], int]:
    """Generate Automatic Zone V1 + evaluate on one HTF series (causal asof)."""
    if not bars:
        return (), (), 0

    resolved_asof = len(bars) - 1 if asof_index is None else asof_index
    if resolved_asof < 0 or resolved_asof >= len(bars):
        return (), (), 0

    prefix = list(bars[: resolved_asof + 1])
    swing_cfg = swing_config or SwingDetectionConfig(2, 2, 2)
    swings_n = _swing_count(prefix, timeframe=timeframe, symbol=symbol)

    generator = AutomaticZoneGenerator(
        swing_config=swing_cfg,
        cluster_config=cluster_config or SwingClusterZoneConfig(),
    )
    zones = generator.generate(
        bars,
        timeframe=timeframe,
        asof_index=resolved_asof,
        instrument=symbol,
    )

    asof_time = bars[resolved_asof].timestamp
    for auto in zones:
        if auto.evidence.origin_confirmation_time > asof_time:
            raise RuntimeError(
                f"future leakage: zone {auto.zone.id} confirmation "
                f"{auto.evidence.origin_confirmation_time} > asof {asof_time}"
            )
        if auto.evidence.asof_index > resolved_asof:
            raise RuntimeError(
                f"future leakage: zone {auto.zone.id} asof_index "
                f"{auto.evidence.asof_index} > {resolved_asof}"
            )

    evaluator = ZoneEvaluator(eval_config or ZoneEvaluationConfig())
    evaluations = evaluator.evaluate(zones, bars, asof_index=resolved_asof)
    return zones, evaluations, swings_n


def _run_window(
    csv_path: Path,
    *,
    symbol: str,
    start: date | None,
    end: date | None,
    timeframes: tuple[str, ...],
    skip_invalid_ohlc: bool,
    allow_partial: bool,
    asof_index: int | None,
    include_zone_details: bool,
) -> tuple[
    dict[str, TimeframeZoneResearchResult],
    AdapterResult,
    dict[str, Any],
    dict[str, tuple[Bar, ...]],
]:
    build_tfs = tuple(dict.fromkeys(("M1", *timeframes)))
    dataset = build_research_dataset(
        csv_path,
        symbol=symbol,
        start=start,
        end=end,
        source_timeframe="M1",
        skip_invalid_ohlc=skip_invalid_ohlc,
        target_timeframes=build_tfs,
        allow_partial=allow_partial,
    )
    adapter_stats = {
        "rows_accepted": dataset.adapter.stats.rows_accepted,
        "rows_dropped_invalid": dataset.adapter.stats.rows_dropped_invalid,
        "timezone_policy": dataset.adapter.stats.timezone_policy,
        "volume_type": dataset.adapter.stats.volume_type,
    }
    dataset_start = start.isoformat() if start else dataset.provenance.get("requested_start")
    dataset_end = end.isoformat() if end else dataset.provenance.get("requested_end")
    if dataset.adapter.stats.first_timestamp is not None:
        dataset_start = dataset.adapter.stats.first_timestamp.date().isoformat()
    if dataset.adapter.stats.last_timestamp is not None:
        dataset_end = dataset.adapter.stats.last_timestamp.date().isoformat()

    by_tf: dict[str, TimeframeZoneResearchResult] = {}
    for tf in timeframes:
        bars = dataset.bars(tf)
        zones, evaluations, swing_n = run_timeframe_pipeline(
            bars,
            timeframe=tf,
            symbol=symbol,
            asof_index=asof_index,
        )
        resample = dataset.resamples.get(tf)
        resample_stats = None
        if resample is not None:
            resample_stats = {
                "emitted_bar_count": resample.stats.emitted_bar_count,
                "skipped_incomplete_buckets": resample.stats.skipped_incomplete_buckets,
                "skipped_closed_buckets": resample.stats.skipped_closed_buckets,
                "completeness_rule": resample.stats.completeness_rule,
                "allow_partial": resample.stats.allow_partial,
            }
        report = _timeframe_report(
            timeframe=tf,
            bars=bars,
            swing_count=swing_n,
            zones=zones,
            evaluations=evaluations,
            source_path=str(csv_path),
            symbol=symbol,
            dataset_provenance=dataset.provenance,
            adapter_stats=adapter_stats,
            volume_type=str(dataset.adapter.stats.volume_type),
            dataset_start=str(dataset_start) if dataset_start else None,
            dataset_end=str(dataset_end) if dataset_end else None,
            resample_stats=resample_stats,
        )
        if not include_zone_details:
            report = {**report, "zones": [], "zone_ids": list(report["zone_ids"])}
        by_tf[tf] = TimeframeZoneResearchResult(
            timeframe=tf,
            bar_count=len(bars),
            swing_count=swing_n,
            zones=zones,
            evaluations=evaluations,
            report=report,
        )
    return by_tf, dataset.adapter, dataset.provenance, {
        tf: dataset.bars(tf) for tf in timeframes
    }


def _segment_snapshot(by_tf: Mapping[str, TimeframeZoneResearchResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tf, result in by_tf.items():
        out[tf] = _compact_tf_metrics(
            bar_count=result.bar_count,
            swing_count=result.swing_count,
            zones=result.zones,
            evaluations=result.evaluations,
        )
    return out


def _rate_spread(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return None
    return max(present) - min(present)


def build_segment_stability(
    csv_path: Path,
    *,
    symbol: str,
    start: date,
    end: date,
    timeframes: tuple[str, ...],
    skip_invalid_ohlc: bool,
    allow_partial: bool,
    include_structure_context: bool = False,
    include_geometry_lifecycle: bool = False,
) -> dict[str, Any]:
    """Run independent first/middle/final third windows and compare metrics."""
    segments = split_date_range_into_thirds(start, end)
    segment_rows: list[dict[str, Any]] = []
    for label, seg_start, seg_end in segments:
        by_tf, _, _, bars_by_tf = _run_window(
            csv_path,
            symbol=symbol,
            start=seg_start,
            end=seg_end,
            timeframes=timeframes,
            skip_invalid_ohlc=skip_invalid_ohlc,
            allow_partial=allow_partial,
            asof_index=None,
            include_zone_details=False,
        )
        row: dict[str, Any] = {
            "label": label,
            "start": seg_start.isoformat(),
            "end": seg_end.isoformat(),
            "by_timeframe": _segment_snapshot(by_tf),
        }
        if include_structure_context and "M15" in by_tf:
            m15 = by_tf["M15"]
            exp = run_structure_context_on_zones(
                m15.zones,
                m15.evaluations,
                bars_by_tf["M15"],
                symbol=symbol,
                timeframe="M15",
                window_start=seg_start,
                window_end=seg_end,
            )
            payload = exp.to_dict()
            payload.pop("contexts", None)
            row["structure_context_experiment"] = payload
        if include_geometry_lifecycle and "M15" in by_tf:
            m15 = by_tf["M15"]
            geo = run_geometry_lifecycle_on_zones(
                m15.zones,
                m15.evaluations,
                bars_by_tf["M15"],
                symbol=symbol,
                timeframe="M15",
                window_start=seg_start,
                window_end=seg_end,
                include_detail_rows=False,
            )
            row["geometry_lifecycle_experiment"] = {
                "experiment_version": geo.to_dict()["experiment_version"],
                "baseline": geo.baseline,
                "aggregates": {
                    "by_width_over_atr": geo.aggregates["by_width_over_atr"],
                    "by_age_to_first_interaction": geo.aggregates[
                        "by_age_to_first_interaction"
                    ],
                    "by_zone_kind": geo.aggregates["by_zone_kind"],
                    "interpretable_width_atr_buckets": geo.aggregates[
                        "interpretable_width_atr_buckets"
                    ],
                    "too_small_width_atr_buckets": geo.aggregates[
                        "too_small_width_atr_buckets"
                    ],
                },
                "diagnosis": geo.diagnosis,
            }
        segment_rows.append(row)

    comparison: dict[str, Any] = {}
    for tf in timeframes:
        success_rates = [
            row["by_timeframe"].get(tf, {}).get("success_rate") for row in segment_rows
        ]
        broken_rates = [
            row["by_timeframe"].get(tf, {}).get("broken_rate") for row in segment_rows
        ]
        failure_rates = [
            row["by_timeframe"].get(tf, {}).get("failure_rate") for row in segment_rows
        ]
        zone_counts = [
            row["by_timeframe"].get(tf, {}).get("zone_count", 0) for row in segment_rows
        ]
        ix_per_zone = [
            row["by_timeframe"].get(tf, {}).get("interactions_per_zone")
            for row in segment_rows
        ]
        median_mfe = [
            row["by_timeframe"].get(tf, {}).get("median_mfe") for row in segment_rows
        ]
        median_mae = [
            row["by_timeframe"].get(tf, {}).get("median_mae") for row in segment_rows
        ]
        widths = [
            row["by_timeframe"].get(tf, {}).get("median_zone_width")
            for row in segment_rows
        ]
        comparison[tf] = {
            "zone_counts": zone_counts,
            "success_rates": success_rates,
            "failure_rates": failure_rates,
            "broken_rates": broken_rates,
            "interactions_per_zone": ix_per_zone,
            "median_mfe": median_mfe,
            "median_mae": median_mae,
            "median_zone_width": widths,
            "success_rate_spread": _rate_spread(success_rates),
            "broken_rate_spread": _rate_spread(broken_rates),
            "failure_rate_spread": _rate_spread(failure_rates),
        }

    structure_alignment_stability: dict[str, Any] = {}
    if include_structure_context:
        for bucket in ("aligned", "opposed", "neutral_unclear"):
            broken = []
            success = []
            for row in segment_rows:
                exp = row.get("structure_context_experiment") or {}
                agg = (exp.get("aggregates") or {}).get("by_alignment", {}).get(bucket, {})
                broken.append(agg.get("broken_rate"))
                success.append(agg.get("success_rate"))
            structure_alignment_stability[bucket] = {
                "broken_rates": broken,
                "success_rates": success,
                "broken_rate_spread": _rate_spread(broken),
                "success_rate_spread": _rate_spread(success),
            }

    geometry_width_atr_stability: dict[str, Any] = {}
    if include_geometry_lifecycle:
        # Collect union of width/ATR bucket labels across segments.
        labels: set[str] = set()
        for row in segment_rows:
            geo = row.get("geometry_lifecycle_experiment") or {}
            labels.update((geo.get("aggregates") or {}).get("by_width_over_atr", {}).keys())
        for bucket in sorted(labels):
            broken = []
            success = []
            for row in segment_rows:
                geo = row.get("geometry_lifecycle_experiment") or {}
                metrics = (geo.get("aggregates") or {}).get("by_width_over_atr", {}).get(
                    bucket, {}
                )
                broken.append(metrics.get("broken_rate"))
                success.append(metrics.get("success_rate"))
            geometry_width_atr_stability[bucket] = {
                "broken_rates": broken,
                "success_rates": success,
                "broken_rate_spread": _rate_spread(broken),
                "success_rate_spread": _rate_spread(success),
            }

    return {
        "segment_count": len(segment_rows),
        "segments": segment_rows,
        "comparison": comparison,
        "structure_alignment_stability": structure_alignment_stability,
        "geometry_width_atr_stability": geometry_width_atr_stability,
        "note": (
            "Segments are independent chronological thirds of the evaluation "
            "window. Rates are zone_eval_v1 outcomes, not predictive accuracy."
        ),
    }


def classify_research_result(
    *,
    by_timeframe: Mapping[str, TimeframeZoneResearchResult],
    segment_stability: Mapping[str, Any],
) -> tuple[str, str]:
    """Classify stability experiment; does not change generation logic."""
    m15 = by_timeframe.get("M15")
    h1 = by_timeframe.get("H1")
    m15_ix = (
        int(m15.report.get("interaction_count") or 0) if m15 is not None else 0
    )
    m15_zones = len(m15.zones) if m15 is not None else 0
    h1_bars = h1.bar_count if h1 is not None else 0
    h1_ix = int(h1.report.get("interaction_count") or 0) if h1 is not None else 0

    if m15 is None or m15_zones < MIN_M15_ZONES or m15_ix < MIN_M15_INTERACTIONS:
        return (
            CLASSIFICATION_INSUFFICIENT,
            (
                f"M15 insufficient for stability judgment "
                f"(zones={m15_zones}, interactions={m15_ix}; "
                f"need zones>={MIN_M15_ZONES}, interactions>={MIN_M15_INTERACTIONS})."
            ),
        )

    comparison = segment_stability.get("comparison", {})
    m15_cmp = comparison.get("M15", {})
    success_spread = m15_cmp.get("success_rate_spread")
    broken_spread = m15_cmp.get("broken_rate_spread")

    unstable = False
    reasons: list[str] = []
    if success_spread is not None and success_spread > MAX_SEGMENT_RATE_SPREAD:
        unstable = True
        reasons.append(
            f"M15 success_rate spread {success_spread:.3f} > {MAX_SEGMENT_RATE_SPREAD}"
        )
    if broken_spread is not None and broken_spread > MAX_SEGMENT_RATE_SPREAD:
        unstable = True
        reasons.append(
            f"M15 broken_rate spread {broken_spread:.3f} > {MAX_SEGMENT_RATE_SPREAD}"
        )

    h1_note = (
        f"H1 usable (bars={h1_bars}, interactions={h1_ix})."
        if h1_bars >= MIN_H1_BARS_FOR_USABLE
        and h1_ix >= MIN_H1_INTERACTIONS_FOR_USABLE
        else (
            f"H1 thin for rates (bars={h1_bars}, interactions={h1_ix}); "
            "M15 is the primary stability signal."
        )
    )

    if unstable:
        return (
            CLASSIFICATION_DIAGNOSTIC,
            "M15 outcome rates vary materially across thirds. "
            + "; ".join(reasons)
            + f". {h1_note}",
        )

    return (
        CLASSIFICATION_STABLE,
        (
            "M15 has enough zones/interactions and outcome rates are sufficiently "
            f"stable across chronological thirds "
            f"(success_spread={success_spread}, broken_spread={broken_spread}). "
            f"{h1_note} Ready for a controlled next experiment — "
            "do not treat rates as predictive accuracy."
        ),
    )


def _deterministic_payload(result_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Strip non-deterministic fields before hashing."""
    payload = json.loads(json.dumps(result_dict, default=str))
    payload.pop("deterministic_hash", None)
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        provenance.pop("generated_at", None)
    # Drop per-zone detail lists for hash stability / size; keep counts & ids.
    tfs = payload.get("timeframes")
    if isinstance(tfs, dict):
        for report in tfs.values():
            if isinstance(report, dict):
                report.pop("zones", None)
    sce = payload.get("structure_context_experiment")
    if isinstance(sce, dict):
        sce.pop("contexts", None)
    geo = payload.get("geometry_lifecycle_experiment")
    if isinstance(geo, dict):
        geo.pop("creations", None)
        geo.pop("lifecycles", None)
        geo.pop("interaction_features", None)
    return payload


def compute_deterministic_hash(result_dict: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _deterministic_payload(result_dict),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_research_zones_smoke(
    csv_path: Path | str,
    *,
    symbol: str = "EURUSD",
    start: date | None = None,
    end: date | None = None,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    skip_invalid_ohlc: bool = True,
    allow_partial: bool = False,
    asof_index: int | None = None,
    include_segment_stability: bool = True,
    include_zone_details: bool = True,
    include_structure_context: bool = True,
    include_geometry_lifecycle: bool = True,
) -> ResearchZonesSmokeResult:
    """End-to-end research evaluation on free OHLC M1 (dataset-bound by default)."""
    path = Path(csv_path)
    tfs = tuple(tf.strip().upper() for tf in timeframes)
    for tf in tfs:
        if tf not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"unsupported timeframe: {tf}")

    bounds, effective_start, effective_end = resolve_evaluation_window(
        path,
        symbol=symbol,
        start=start,
        end=end,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )

    by_tf, adapter, dataset_provenance, bars_by_tf = _run_window(
        path,
        symbol=symbol,
        start=effective_start,
        end=effective_end,
        timeframes=tfs,
        skip_invalid_ohlc=skip_invalid_ohlc,
        allow_partial=allow_partial,
        asof_index=asof_index,
        include_zone_details=include_zone_details,
    )

    # Window-scoped bounds for provenance (accepted bars in effective range).
    window_bounds = DatasetBounds(
        source_path=str(path),
        symbol=symbol.strip().upper(),
        first_timestamp=adapter.stats.first_timestamp,
        last_timestamp=adapter.stats.last_timestamp,
        first_date=(
            None
            if adapter.stats.first_timestamp is None
            else adapter.stats.first_timestamp.date()
        ),
        last_date=(
            None
            if adapter.stats.last_timestamp is None
            else adapter.stats.last_timestamp.date()
        ),
        accepted_m1_bars=int(adapter.stats.rows_accepted),
        dropped_invalid_bars=int(adapter.stats.rows_dropped_invalid),
        volume_type=str(adapter.stats.volume_type),
        timezone_policy=str(adapter.stats.timezone_policy),
    )

    structure_context_experiment: dict[str, Any] | None = None
    if include_structure_context and "M15" in by_tf:
        m15 = by_tf["M15"]
        if m15.bar_count > 0:
            exp = run_structure_context_on_zones(
                m15.zones,
                m15.evaluations,
                bars_by_tf["M15"],
                symbol=symbol,
                timeframe="M15",
                window_start=effective_start,
                window_end=effective_end,
            )
            structure_context_experiment = exp.to_dict()
            # Attach compact bucket summary onto M15 report.
            m15.report["structure_context_buckets"] = {
                "by_structure": exp.aggregates["by_structure"],
                "by_alignment": exp.aggregates["by_alignment"],
                "too_small_structure_buckets": exp.aggregates[
                    "too_small_structure_buckets"
                ],
                "too_small_alignment_buckets": exp.aggregates[
                    "too_small_alignment_buckets"
                ],
                "diagnosis": exp.diagnosis,
            }

    geometry_lifecycle_experiment: dict[str, Any] | None = None
    if include_geometry_lifecycle and "M15" in by_tf:
        m15 = by_tf["M15"]
        if m15.bar_count > 0:
            geo = run_geometry_lifecycle_on_zones(
                m15.zones,
                m15.evaluations,
                bars_by_tf["M15"],
                symbol=symbol,
                timeframe="M15",
                window_start=effective_start,
                window_end=effective_end,
                include_detail_rows=True,
            )
            geometry_lifecycle_experiment = geo.to_dict()
            m15.report["geometry_lifecycle_buckets"] = {
                "by_width_over_atr": geo.aggregates["by_width_over_atr"],
                "by_age_to_first_interaction": geo.aggregates[
                    "by_age_to_first_interaction"
                ],
                "by_zone_kind": geo.aggregates["by_zone_kind"],
                "diagnosis": geo.diagnosis,
            }

    segment_stability: dict[str, Any]
    if (
        include_segment_stability
        and effective_start is not None
        and effective_end is not None
        and any(r.bar_count > 0 for r in by_tf.values())
    ):
        segment_stability = build_segment_stability(
            path,
            symbol=symbol,
            start=effective_start,
            end=effective_end,
            timeframes=tfs,
            skip_invalid_ohlc=skip_invalid_ohlc,
            allow_partial=allow_partial,
            include_structure_context=include_structure_context and "M15" in tfs,
            include_geometry_lifecycle=include_geometry_lifecycle and "M15" in tfs,
        )
    else:
        segment_stability = {
            "segment_count": 0,
            "segments": [],
            "comparison": {},
            "note": "Segment stability skipped (empty window or disabled).",
        }

    classification, rationale = classify_research_result(
        by_timeframe=by_tf,
        segment_stability=segment_stability,
    )

    all_zones = [z for r in by_tf.values() for z in r.zones]
    all_evals = [e for r in by_tf.values() for e in r.evaluations]
    outcomes = _outcome_counts(all_evals)
    widths = [z.zone.high - z.zone.low for z in all_zones]
    strengths = [float(z.zone.strength) for z in all_zones]
    touches = [float(z.evidence.touch_count) for z in all_zones]
    mfes = [e.median_mfe for e in all_evals if e.median_mfe is not None]
    maes = [e.median_mae for e in all_evals if e.median_mae is not None]

    summary = {
        "zones_generated": len(all_zones),
        "zones_evaluated": len(all_evals),
        "success_count": outcomes["SUCCESS_count"],
        "failure_count": outcomes["FAILURE_count"],
        "broken_count": outcomes["BROKEN_count"],
        "unavailable_count": outcomes["UNAVAILABLE_count"],
        "interaction_count": outcomes["interaction_count"],
        "success_rate": outcomes["success_rate"],
        "failure_rate": outcomes["failure_rate"],
        "broken_rate": outcomes["broken_rate"],
        "unavailable_rate": outcomes["unavailable_rate"],
        "average_touches": mean(touches) if touches else None,
        "median_touches": median(touches) if touches else None,
        "average_zone_width": mean(widths) if widths else None,
        "average_strength": mean(strengths) if strengths else None,
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
        "disclaimer": (
            "Rates are zone outcome evaluation under zone_eval_v1, "
            "not predictive accuracy."
        ),
        "by_timeframe": {
            tf: {
                "bar_count": r.bar_count,
                "swing_count": r.swing_count,
                "zones": len(r.zones),
                "supply": sum(1 for z in r.zones if z.zone.kind == ZoneKind.SUPPLY),
                "demand": sum(1 for z in r.zones if z.zone.kind == ZoneKind.DEMAND),
                "interaction_count": r.report.get("interaction_count"),
                "success_rate": r.report.get("success_rate"),
                "broken_rate": r.report.get("broken_rate"),
            }
            for tf, r in by_tf.items()
        },
        "research_classification": classification,
        "structure_context_conclusion": (
            None
            if structure_context_experiment is None
            else structure_context_experiment.get("diagnosis", {}).get(
                "conclusion_code"
            )
        ),
        "geometry_lifecycle_conclusion": (
            None
            if geometry_lifecycle_experiment is None
            else geometry_lifecycle_experiment.get("diagnosis", {}).get(
                "conclusion_code"
            )
        ),
    }

    provenance = {
        "pipeline_version": PIPELINE_VERSION,
        "zone_method_id": METHOD_SWING_CLUSTER_ZONE_V1,
        "evaluation_method_id": METHOD_ZONE_EVAL_V1,
        "dataset": dataset_provenance,
        "dataset_bounds_full_file": bounds.to_dict(),
        "adapter_stats": {
            "rows_accepted": adapter.stats.rows_accepted,
            "rows_dropped_invalid": adapter.stats.rows_dropped_invalid,
            "timezone_policy": adapter.stats.timezone_policy,
            "volume_type": adapter.stats.volume_type,
        },
        "volume_note": (
            "Dataset volume_type is tick_volume; preserved on bars, "
            "not used for zone generation in this experiment."
        ),
        "structure_context_note": (
            "M15 zones labeled with FeatureRepository+TrendView "
            "market_structure_v1 at origin_confirmation_time only."
        ),
        "geometry_lifecycle_note": (
            "M15 geometry/lifecycle diagnostics use causal_atr at creation "
            "and zone_eval_v1 interactions; evaluator semantics unchanged."
        ),
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
        + "Z",
    }

    result = ResearchZonesSmokeResult(
        source_path=str(path),
        symbol=symbol.strip().upper(),
        requested_start=start.isoformat() if start else None,
        requested_end=end.isoformat() if end else None,
        effective_start=effective_start.isoformat() if effective_start else None,
        effective_end=effective_end.isoformat() if effective_end else None,
        dataset_bounds=window_bounds,
        by_timeframe=by_tf,
        summary=summary,
        provenance=provenance,
        segment_stability=segment_stability,
        structure_context_experiment=structure_context_experiment,
        geometry_lifecycle_experiment=geometry_lifecycle_experiment,
        research_classification=classification,
        classification_rationale=rationale,
        deterministic_hash="",  # filled below
    )
    payload = result.to_dict()
    digest = compute_deterministic_hash(payload)
    return ResearchZonesSmokeResult(
        source_path=result.source_path,
        symbol=result.symbol,
        requested_start=result.requested_start,
        requested_end=result.requested_end,
        effective_start=result.effective_start,
        effective_end=result.effective_end,
        dataset_bounds=result.dataset_bounds,
        by_timeframe=result.by_timeframe,
        summary=result.summary,
        provenance=result.provenance,
        segment_stability=result.segment_stability,
        structure_context_experiment=result.structure_context_experiment,
        geometry_lifecycle_experiment=result.geometry_lifecycle_experiment,
        research_classification=result.research_classification,
        classification_rationale=result.classification_rationale,
        deterministic_hash=digest,
    )
