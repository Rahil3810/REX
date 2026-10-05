"""Research experiment: Automatic Zone V1 outcomes vs causal market structure.

Does NOT modify Automatic Zone V1 or Zone Evaluation V1.
Uses FeatureRepository + TrendView (market_structure_v1) at each zone's
origin_confirmation_time only — no future bars or outcomes influence labels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from statistics import mean, median
from typing import Any, Mapping, Sequence

from core.features import (
    METHOD_TREND_MARKET_STRUCTURE_V1,
    PACK_STRUCTURE,
    FeatureRepository,
    TrendView,
)
from core.features.config import FeatureConfig, default_feature_config
from core.zones import AutomaticZone, ZoneEvaluation
from models.bar import Bar
from models.market_structure import MarketTrend
from models.zone import ZoneKind

EXPERIMENT_VERSION = "structure_zone_context_v1"
METHOD_ID = str(METHOD_TREND_MARKET_STRUCTURE_V1)

# Prominence thresholds — buckets below these are marked too_small_to_interpret.
MIN_INTERPRETABLE_ZONES = 20
MIN_INTERPRETABLE_INTERACTIONS = 50

STRUCTURE_BULLISH = "bullish"
STRUCTURE_BEARISH = "bearish"
STRUCTURE_NEUTRAL = "neutral_unclear"

ALIGNMENT_ALIGNED = "aligned"
ALIGNMENT_OPPOSED = "opposed"
ALIGNMENT_NEUTRAL = "neutral_unclear"


def entry_only_feature_config() -> FeatureConfig:
    """Entry-TF structure only (no HTF aggregation) for this diagnostic."""
    base = default_feature_config()
    return replace(
        base,
        multi_timeframe_mapping={
            **base.multi_timeframe_mapping,
            "M15": (),
            "H1": (),
            "H4": (),
            "D1": (),
        },
    )


@dataclass(frozen=True)
class ZoneStructureContext:
    """Causal structure labels for one automatic zone at creation time."""

    zone_id: int
    zone_kind: str | None
    origin_confirmation_index: int
    origin_confirmation_time: str
    market_trend: str
    structure_bucket: str
    alignment_bucket: str
    structure_score: int
    trend_reason: str
    method_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_kind": self.zone_kind,
            "origin_confirmation_index": self.origin_confirmation_index,
            "origin_confirmation_time": self.origin_confirmation_time,
            "market_trend": self.market_trend,
            "structure_bucket": self.structure_bucket,
            "alignment_bucket": self.alignment_bucket,
            "structure_score": self.structure_score,
            "trend_reason": self.trend_reason,
            "method_id": self.method_id,
            "note": (
                "structure_score is a categorical config lookup, not confidence. "
                "Labels use only bars available at origin_confirmation_time."
            ),
        }


def structure_bucket_from_trend(trend: MarketTrend) -> str:
    if trend == MarketTrend.BULLISH:
        return STRUCTURE_BULLISH
    if trend == MarketTrend.BEARISH:
        return STRUCTURE_BEARISH
    return STRUCTURE_NEUTRAL


def alignment_bucket_from_zone_and_trend(
    zone_kind: ZoneKind | None,
    trend: MarketTrend,
) -> str:
    """Map DEMAND↔bullish and SUPPLY↔bearish; else neutral_unclear."""
    if trend in (MarketTrend.RANGING, MarketTrend.UNKNOWN) or zone_kind is None:
        return ALIGNMENT_NEUTRAL
    if zone_kind == ZoneKind.DEMAND and trend == MarketTrend.BULLISH:
        return ALIGNMENT_ALIGNED
    if zone_kind == ZoneKind.SUPPLY and trend == MarketTrend.BEARISH:
        return ALIGNMENT_ALIGNED
    if zone_kind == ZoneKind.DEMAND and trend == MarketTrend.BEARISH:
        return ALIGNMENT_OPPOSED
    if zone_kind == ZoneKind.SUPPLY and trend == MarketTrend.BULLISH:
        return ALIGNMENT_OPPOSED
    return ALIGNMENT_NEUTRAL


def classify_zone_structure_context(
    auto: AutomaticZone,
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str = "M15",
    repository: FeatureRepository | None = None,
    trend_view: TrendView | None = None,
) -> ZoneStructureContext:
    """Attach causal market_structure_v1 context at zone creation time."""
    repo = repository or FeatureRepository(entry_only_feature_config())
    view = trend_view or TrendView(repo.config)
    asof = auto.evidence.origin_confirmation_time

    # Guard: confirmation index must be within bars and match asof open.
    conf_i = auto.evidence.origin_confirmation_index
    if conf_i < 0 or conf_i >= len(bars):
        trend = MarketTrend.UNKNOWN
        reason = "origin_confirmation_index outside bar series"
        score = 0
    else:
        # Pass full series; materialize(asof=T) filters future bars.
        ctx = repo.materialize(
            symbol,
            {timeframe: bars},
            entry_timeframe=timeframe,
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        # Causal assertion: no bar open after asof.
        for tf_bars in ctx.bars_by_timeframe.values():
            for bar in tf_bars:
                bar_ts = bar.timestamp
                asof_cmp = asof
                if bar_ts.tzinfo is None and asof_cmp.tzinfo is not None:
                    asof_cmp = asof_cmp.replace(tzinfo=None)
                elif bar_ts.tzinfo is not None and asof_cmp.tzinfo is None:
                    from datetime import timezone

                    asof_cmp = asof_cmp.replace(tzinfo=timezone.utc)
                if bar_ts > asof_cmp:
                    raise RuntimeError(
                        f"lookahead in FeatureContext: bar {bar_ts} > asof {asof}"
                    )
        projection = view.project(ctx, METHOD_TREND_MARKET_STRUCTURE_V1)
        trend = projection.trend
        reason = projection.reason
        score = int(projection.structure_score)

    return ZoneStructureContext(
        zone_id=auto.zone.id,
        zone_kind=None if auto.zone.kind is None else auto.zone.kind.value,
        origin_confirmation_index=conf_i,
        origin_confirmation_time=asof.isoformat(sep=" "),
        market_trend=trend.value,
        structure_bucket=structure_bucket_from_trend(trend),
        alignment_bucket=alignment_bucket_from_zone_and_trend(auto.zone.kind, trend),
        structure_score=score,
        trend_reason=reason,
        method_id=METHOD_ID,
    )


def _safe_rate(num: int, den: int) -> float | None:
    return (num / den) if den else None


def _bucket_metrics(
    *,
    bucket_key: str,
    bucket_value: str,
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    contexts: Sequence[ZoneStructureContext],
    selected_contexts: Sequence[ZoneStructureContext] | None = None,
) -> dict[str, Any]:
    eval_by_id = {e.zone_id: e for e in evaluations}
    if selected_contexts is not None:
        selected = list(selected_contexts)
    else:
        selected = [c for c in contexts if getattr(c, bucket_key) == bucket_value]
    selected_ids = {c.zone_id for c in selected}
    selected_zones = [z for z in zones if z.zone.id in selected_ids]
    selected_evals = [eval_by_id[zid] for zid in selected_ids if zid in eval_by_id]

    success = sum(e.successful_reaction_count for e in selected_evals)
    failure = sum(e.failed_reaction_count for e in selected_evals)
    broken = sum(e.broken_count for e in selected_evals)
    unavailable = sum(e.unavailable_count for e in selected_evals)
    interactions = sum(e.sample_count for e in selected_evals)
    decisive = success + failure + broken

    touches = [float(z.evidence.touch_count) for z in selected_zones]
    mfes = [e.median_mfe for e in selected_evals if e.median_mfe is not None]
    maes = [e.median_mae for e in selected_evals if e.median_mae is not None]
    ix_mfes = [
        float(ix.mfe)
        for e in selected_evals
        for ix in e.interactions
        if ix.mfe is not None
    ]
    ix_maes = [
        float(ix.mae)
        for e in selected_evals
        for ix in e.interactions
        if ix.mae is not None
    ]

    too_small = (
        len(selected_zones) < MIN_INTERPRETABLE_ZONES
        or interactions < MIN_INTERPRETABLE_INTERACTIONS
    )
    return {
        "bucket_key": bucket_key,
        "bucket": bucket_value,
        "zone_count": len(selected_zones),
        "interaction_count": interactions,
        "SUCCESS_count": success,
        "FAILURE_count": failure,
        "BROKEN_count": broken,
        "UNAVAILABLE_count": unavailable,
        "success_rate": _safe_rate(success, decisive),
        "failure_rate": _safe_rate(failure, decisive),
        "broken_rate": _safe_rate(broken, decisive),
        "unavailable_rate": _safe_rate(unavailable, interactions),
        "average_touches": mean(touches) if touches else None,
        "median_touches": median(touches) if touches else None,
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
        "interaction_median_mfe": median(ix_mfes) if ix_mfes else None,
        "interaction_median_mae": median(ix_maes) if ix_maes else None,
        "sample_size": {
            "zones": len(selected_zones),
            "interactions": interactions,
            "decisive_outcomes": decisive,
            "min_zones_for_interpretation": MIN_INTERPRETABLE_ZONES,
            "min_interactions_for_interpretation": MIN_INTERPRETABLE_INTERACTIONS,
            "too_small_to_interpret": too_small,
        },
        "disclaimer": (
            "Rates are zone_eval_v1 outcomes stratified by causal structure "
            "context — not predictive accuracy."
        ),
    }


def aggregate_structure_buckets(
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    contexts: Sequence[ZoneStructureContext],
) -> dict[str, Any]:
    structure_values = (STRUCTURE_BULLISH, STRUCTURE_BEARISH, STRUCTURE_NEUTRAL)
    alignment_values = (ALIGNMENT_ALIGNED, ALIGNMENT_OPPOSED, ALIGNMENT_NEUTRAL)

    by_structure = {
        value: _bucket_metrics(
            bucket_key="structure_bucket",
            bucket_value=value,
            zones=zones,
            evaluations=evaluations,
            contexts=contexts,
        )
        for value in structure_values
    }
    by_alignment = {
        value: _bucket_metrics(
            bucket_key="alignment_bucket",
            bucket_value=value,
            zones=zones,
            evaluations=evaluations,
            contexts=contexts,
        )
        for value in alignment_values
    }

    # Joint buckets for diagnostic detail (sample sizes often smaller).
    joint: dict[str, Any] = {}
    for s in structure_values:
        for a in alignment_values:
            key = f"{s}__{a}"
            matched = [
                c
                for c in contexts
                if c.structure_bucket == s and c.alignment_bucket == a
            ]
            joint[key] = _joint_metrics(key, matched, zones, evaluations)

    return {
        "by_structure": by_structure,
        "by_alignment": by_alignment,
        "by_structure_and_alignment": joint,
        "interpretable_structure_buckets": [
            k
            for k, v in by_structure.items()
            if not v["sample_size"]["too_small_to_interpret"]
        ],
        "interpretable_alignment_buckets": [
            k
            for k, v in by_alignment.items()
            if not v["sample_size"]["too_small_to_interpret"]
        ],
        "too_small_structure_buckets": [
            k
            for k, v in by_structure.items()
            if v["sample_size"]["too_small_to_interpret"]
        ],
        "too_small_alignment_buckets": [
            k
            for k, v in by_alignment.items()
            if v["sample_size"]["too_small_to_interpret"]
        ],
    }


def _joint_metrics(
    key: str,
    matched: Sequence[ZoneStructureContext],
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
) -> dict[str, Any]:
    return _bucket_metrics(
        bucket_key="structure_alignment",
        bucket_value=key,
        zones=zones,
        evaluations=evaluations,
        contexts=matched,
        selected_contexts=matched,
    )


def diagnose_structure_explanation(
    aggregates: Mapping[str, Any],
) -> dict[str, Any]:
    """Answer whether structure appears to explain high broken rates.

    Diagnostic only — does not recommend algorithm changes automatically.
    """
    by_align = aggregates.get("by_alignment", {})
    aligned = by_align.get(ALIGNMENT_ALIGNED, {})
    opposed = by_align.get(ALIGNMENT_OPPOSED, {})
    neutral = by_align.get(ALIGNMENT_NEUTRAL, {})

    aligned_ok = not aligned.get("sample_size", {}).get("too_small_to_interpret", True)
    opposed_ok = not opposed.get("sample_size", {}).get("too_small_to_interpret", True)
    neutral_ok = not neutral.get("sample_size", {}).get("too_small_to_interpret", True)

    a_broken = aligned.get("broken_rate")
    o_broken = opposed.get("broken_rate")
    n_broken = neutral.get("broken_rate")
    a_success = aligned.get("success_rate")
    o_success = opposed.get("success_rate")

    material_gap = 0.10  # absolute rate gap to treat as noteworthy
    notes: list[str] = []

    if not (aligned_ok and opposed_ok):
        conclusion = (
            "INCONCLUSIVE_SAMPLE"
        )
        answer = (
            "No — sample sizes for aligned and/or opposed buckets are too small "
            "to justify a structure-conditioned Zone V1 experiment."
        )
        notes.append(
            f"aligned too_small={not aligned_ok} "
            f"(zones={aligned.get('zone_count')}, ix={aligned.get('interaction_count')}); "
            f"opposed too_small={not opposed_ok} "
            f"(zones={opposed.get('zone_count')}, ix={opposed.get('interaction_count')})"
        )
    else:
        broken_delta = None
        success_delta = None
        if a_broken is not None and o_broken is not None:
            broken_delta = abs(a_broken - o_broken)
            notes.append(
                f"aligned broken_rate={a_broken:.4f}, opposed broken_rate={o_broken:.4f}, "
                f"|delta|={broken_delta:.4f}"
            )
        if a_success is not None and o_success is not None:
            success_delta = abs(a_success - o_success)
            notes.append(
                f"aligned success_rate={a_success:.4f}, opposed success_rate={o_success:.4f}, "
                f"|delta|={success_delta:.4f}"
            )
        if neutral_ok and n_broken is not None:
            notes.append(f"neutral_unclear broken_rate={n_broken:.4f}")

        explains = (
            broken_delta is not None
            and broken_delta >= material_gap
        ) or (
            success_delta is not None
            and success_delta >= material_gap
        )
        if explains:
            conclusion = "STRUCTURE_APPEARS_MATERIAL"
            answer = (
                "Yes — aligned vs opposed outcome rates differ enough, with "
                "adequate samples, to justify a subsequent *controlled* "
                "structure-aware Zone V1 experiment. This is not proof that "
                "structure fixes the broken rate."
            )
        else:
            conclusion = "STRUCTURE_DOES_NOT_EXPLAIN_ENOUGH"
            answer = (
                "No — market-structure context does not appear to explain the "
                "high broken-zone rate enough to justify changing Zone V1 yet. "
                "Aligned and opposed broken/success rates are similar (or the "
                "gap is below the diagnostic threshold)."
            )

    return {
        "conclusion_code": conclusion,
        "answers_research_question": answer,
        "research_question": (
            "Does market-structure context appear to explain the high "
            "broken-zone rate enough to justify a subsequent controlled "
            "Zone V1 experiment?"
        ),
        "material_gap_threshold": material_gap,
        "aligned_broken_rate": a_broken,
        "opposed_broken_rate": o_broken,
        "neutral_broken_rate": n_broken,
        "aligned_success_rate": a_success,
        "opposed_success_rate": o_success,
        "notes": notes,
        "disclaimer": (
            "Diagnostic stratification only. Not predictive accuracy. "
            "Do not optimize Zone V1 from this report alone."
        ),
    }


@dataclass(frozen=True)
class StructureContextExperimentResult:
    timeframe: str
    window_start: str | None
    window_end: str | None
    contexts: tuple[ZoneStructureContext, ...]
    aggregates: dict[str, Any]
    diagnosis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "timeframe": self.timeframe,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "method_id": METHOD_ID,
            "zone_count": len(self.contexts),
            "contexts": [c.to_dict() for c in self.contexts],
            "aggregates": self.aggregates,
            "diagnosis": self.diagnosis,
            "disclaimer": (
                "Causal structure labels at origin_confirmation_time; "
                "zone_eval_v1 outcomes stratified for diagnosis only."
            ),
        }


def run_structure_context_on_zones(
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str = "M15",
    window_start: date | str | None = None,
    window_end: date | str | None = None,
) -> StructureContextExperimentResult:
    """Classify each zone and aggregate evaluation outcomes by structure."""
    repo = FeatureRepository(entry_only_feature_config())
    view = TrendView(repo.config)
    contexts = tuple(
        classify_zone_structure_context(
            auto,
            bars,
            symbol=symbol,
            timeframe=timeframe,
            repository=repo,
            trend_view=view,
        )
        for auto in zones
    )
    aggregates = aggregate_structure_buckets(zones, evaluations, contexts)
    diagnosis = diagnose_structure_explanation(aggregates)
    return StructureContextExperimentResult(
        timeframe=timeframe,
        window_start=None if window_start is None else str(window_start),
        window_end=None if window_end is None else str(window_end),
        contexts=contexts,
        aggregates=aggregates,
        diagnosis=diagnosis,
    )
