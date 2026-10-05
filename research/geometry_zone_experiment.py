"""Research diagnostic: Zone V1 outcomes vs causal geometry / lifecycle.

Does NOT modify Automatic Zone V1 or Zone Evaluation V1.
Creation-time features use only bars available at origin_confirmation_index.
Interaction-time features are clearly separated and use interaction asof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean, median
from typing import Any, Mapping, Sequence

from core.features.config import SwingDetectionConfig
from core.features.generators.swings import SwingGenerator, SwingKind
from core.market import require_instrument
from core.zones import AutomaticZone, ZoneEvaluation, ZoneInteractionEvaluation
from core.zones.auto.atr import causal_atr
from core.zones.evaluation.models import InteractionOutcome
from models.bar import Bar
from models.zone import ZoneKind

EXPERIMENT_VERSION = "geometry_lifecycle_zone_v1"
ATR_PERIOD = 14
RECENT_RANGE_BARS = 5

MIN_INTERPRETABLE_ZONES = 20
MIN_INTERPRETABLE_INTERACTIONS = 50
MATERIAL_GAP = 0.10

# Predeclared buckets — do not search for better thresholds.
WIDTH_ATR_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("lt_0.5", None, 0.5),
    ("0.5_to_1", 0.5, 1.0),
    ("1_to_2", 1.0, 2.0),
    ("gt_2", 2.0, None),
    ("atr_unavailable", None, None),  # special
)

# M15: 4 bars/hour. Age buckets in bars.
AGE_BUCKETS_BARS: tuple[tuple[str, int | None, int | None], ...] = (
    ("lt_1h", None, 4),
    ("1h_to_4h", 4, 16),
    ("4h_to_24h", 16, 96),
    ("gt_24h", 96, None),
    ("no_interaction", None, None),  # special
)

TOUCH_BUCKETS: tuple[str, ...] = ("0", "1", "2", "3_plus")


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


def zone_width(auto: AutomaticZone) -> float:
    return float(auto.zone.high - auto.zone.low)


def recent_range(
    bars: Sequence[Bar],
    *,
    asof_index: int,
    lookback: int = RECENT_RANGE_BARS,
) -> float | None:
    """High-low range over the last ``lookback`` bars ending at asof (inclusive)."""
    if asof_index < 0 or asof_index >= len(bars) or lookback < 1:
        return None
    start = max(0, asof_index - lookback + 1)
    window = bars[start : asof_index + 1]
    if not window:
        return None
    return float(max(b.high for b in window) - min(b.low for b in window))


def width_atr_bucket(width_over_atr: float | None) -> str:
    if width_over_atr is None:
        return "atr_unavailable"
    if width_over_atr < 0.5:
        return "lt_0.5"
    if width_over_atr < 1.0:
        return "0.5_to_1"
    if width_over_atr < 2.0:
        return "1_to_2"
    return "gt_2"


def age_bars_bucket(age_bars: int | None) -> str:
    if age_bars is None:
        return "no_interaction"
    if age_bars < 4:
        return "lt_1h"
    if age_bars < 16:
        return "1h_to_4h"
    if age_bars < 96:
        return "4h_to_24h"
    return "gt_24h"


def touch_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n == 1:
        return "1"
    if n == 2:
        return "2"
    return "3_plus"


def penetration_at_entry(
    zone_low: float,
    zone_high: float,
    kind: ZoneKind | None,
    bar: Bar,
) -> dict[str, Any]:
    """Research-local penetration metrics from entry bar OHLC (evaluator unchanged)."""
    width = zone_high - zone_low
    overlap = max(0.0, min(bar.high, zone_high) - max(bar.low, zone_low))
    close_inside = zone_low <= bar.close <= zone_high
    if kind == ZoneKind.DEMAND:
        # How far price traded through the band from the top edge.
        wick_depth = max(0.0, zone_high - bar.low)
        close_through = bar.close < zone_low
        far_excursion = max(0.0, zone_low - bar.low) if bar.low < zone_low else 0.0
    elif kind == ZoneKind.SUPPLY:
        wick_depth = max(0.0, bar.high - zone_low)
        close_through = bar.close > zone_high
        far_excursion = max(0.0, bar.high - zone_high) if bar.high > zone_high else 0.0
    else:
        wick_depth = overlap
        close_through = False
        far_excursion = 0.0

    wick_only = overlap > 0 and not close_inside and not close_through
    return {
        "overlap": overlap,
        "wick_depth": wick_depth,
        "wick_depth_over_width": (wick_depth / width) if width > 0 else None,
        "overlap_over_width": (overlap / width) if width > 0 else None,
        "close_inside": close_inside,
        "close_through": close_through,
        "wick_only_penetration": wick_only,
        "far_boundary_excursion": far_excursion,
        "far_boundary_excursion_over_width": (
            (far_excursion / width) if width > 0 else None
        ),
    }


def originating_swing_metrics(
    bars: Sequence[Bar],
    auto: AutomaticZone,
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Causal origin-swing diagnostics at confirmation (reuse SwingGenerator)."""
    conf_i = auto.evidence.origin_confirmation_index
    if conf_i < 0 or conf_i >= len(bars):
        return {
            "origin_swing_price": None,
            "origin_bar_range": None,
            "origin_to_zone_mid": None,
            "prior_opposite_swing_distance": None,
        }

    prefix = bars[: conf_i + 1]
    origin_bar = bars[auto.evidence.origin_index] if 0 <= auto.evidence.origin_index < len(bars) else None
    origin_bar_range = (
        None if origin_bar is None else float(origin_bar.high - origin_bar.low)
    )

    features = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
        {timeframe: list(prefix)},
        require_instrument(symbol),
        entry_timeframe=timeframe,
        asof=bars[conf_i].timestamp,
    )
    swings = features.by_timeframe[timeframe].swings
    origin = next((s for s in swings if s.id == auto.evidence.origin_swing_id), None)
    if origin is None:
        # Fallback: match by index/kind from id is unavailable — use origin_index bar mid.
        price = None if origin_bar is None else float(origin_bar.close)
        return {
            "origin_swing_price": price,
            "origin_bar_range": origin_bar_range,
            "origin_to_zone_mid": (
                None
                if price is None
                else abs(price - (auto.zone.low + auto.zone.high) / 2.0)
            ),
            "prior_opposite_swing_distance": None,
        }

    mid = (auto.zone.low + auto.zone.high) / 2.0
    opposite_kind = SwingKind.LOW if origin.kind == SwingKind.HIGH else SwingKind.HIGH
    prior_opp = [
        s
        for s in swings
        if s.kind == opposite_kind and s.confirmation_index <= conf_i and s.index < origin.index
    ]
    prior_distance = None
    if prior_opp:
        prior_distance = abs(origin.price - prior_opp[-1].price)

    return {
        "origin_swing_price": float(origin.price),
        "origin_bar_range": origin_bar_range,
        "origin_to_zone_mid": abs(float(origin.price) - mid),
        "prior_opposite_swing_distance": prior_distance,
    }


@dataclass(frozen=True)
class ZoneCreationGeometry:
    """Creation-time geometry — no future interactions/outcomes."""

    zone_id: int
    zone_kind: str | None
    origin_confirmation_index: int
    origin_confirmation_time: str
    absolute_width: float
    atr_at_creation: float | None
    width_over_atr: float | None
    width_atr_bucket: str
    recent_range: float | None
    width_over_recent_range: float | None
    contributing_swing_count: int
    ranking_strength: int
    departure_move: float | None
    cluster_tolerance: float
    origin_swing_price: float | None
    origin_bar_range: float | None
    origin_to_zone_mid: float | None
    prior_opposite_swing_distance: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_kind": self.zone_kind,
            "origin_confirmation_index": self.origin_confirmation_index,
            "origin_confirmation_time": self.origin_confirmation_time,
            "absolute_width": self.absolute_width,
            "atr_at_creation": self.atr_at_creation,
            "width_over_atr": self.width_over_atr,
            "width_atr_bucket": self.width_atr_bucket,
            "recent_range": self.recent_range,
            "width_over_recent_range": self.width_over_recent_range,
            "contributing_swing_count": self.contributing_swing_count,
            "ranking_strength": self.ranking_strength,
            "departure_move": self.departure_move,
            "cluster_tolerance": self.cluster_tolerance,
            "origin_swing_price": self.origin_swing_price,
            "origin_bar_range": self.origin_bar_range,
            "origin_to_zone_mid": self.origin_to_zone_mid,
            "prior_opposite_swing_distance": self.prior_opposite_swing_distance,
            "note": (
                "Creation-time ATR/range use origin_confirmation_index only. "
                "Zone bounds/strength/departure come from the evaluated V1 zone "
                "object (same object as outcomes); ATR normalization is causal."
            ),
        }


@dataclass(frozen=True)
class ZoneLifecycleFeatures:
    """Lifecycle features derived from evaluation interactions (post-creation)."""

    zone_id: int
    interaction_count: int
    age_bars_to_first_interaction: int | None
    age_bucket_first_interaction: str
    interactions_before_first_decisive: int | None
    first_outcome: str | None
    prior_touches_before_decisive: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "interaction_count": self.interaction_count,
            "age_bars_to_first_interaction": self.age_bars_to_first_interaction,
            "age_bucket_first_interaction": self.age_bucket_first_interaction,
            "interactions_before_first_decisive": self.interactions_before_first_decisive,
            "first_outcome": self.first_outcome,
            "prior_touches_before_decisive": self.prior_touches_before_decisive,
            "note": (
                "Lifecycle ages use interaction entry_index vs origin_confirmation; "
                "outcomes remain zone_eval_v1 labels."
            ),
        }


@dataclass(frozen=True)
class InteractionGeometryFeatures:
    """Interaction-time diagnostics (separated from creation-time)."""

    zone_id: int
    interaction_index: int
    entry_index: int
    age_bars_at_interaction: int
    prior_touches: int
    outcome: str
    break_detected: bool
    atr_at_interaction: float | None
    mfe: float | None
    mae: float | None
    mfe_over_atr: float | None
    mae_over_atr: float | None
    penetration: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "interaction_index": self.interaction_index,
            "entry_index": self.entry_index,
            "age_bars_at_interaction": self.age_bars_at_interaction,
            "prior_touches": self.prior_touches,
            "prior_touches_bucket": touch_bucket(self.prior_touches),
            "outcome": self.outcome,
            "break_detected": self.break_detected,
            "atr_at_interaction": self.atr_at_interaction,
            "mfe": self.mfe,
            "mae": self.mae,
            "mfe_over_atr": self.mfe_over_atr,
            "mae_over_atr": self.mae_over_atr,
            "penetration": self.penetration,
            "note": "Interaction-time only; does not redefine zone_eval_v1 outcomes.",
        }


def compute_creation_geometry(
    auto: AutomaticZone,
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str = "M15",
    atr_period: int = ATR_PERIOD,
) -> ZoneCreationGeometry:
    conf_i = auto.evidence.origin_confirmation_index
    width = zone_width(auto)
    atr = causal_atr(bars, asof_index=conf_i, period=atr_period)
    w_atr = (width / atr) if atr is not None and atr > 0 else None
    rr = recent_range(bars, asof_index=conf_i)
    origin = originating_swing_metrics(
        bars, auto, symbol=symbol, timeframe=timeframe
    )
    return ZoneCreationGeometry(
        zone_id=auto.zone.id,
        zone_kind=None if auto.zone.kind is None else auto.zone.kind.value,
        origin_confirmation_index=conf_i,
        origin_confirmation_time=auto.evidence.origin_confirmation_time.isoformat(sep=" "),
        absolute_width=width,
        atr_at_creation=atr,
        width_over_atr=w_atr,
        width_atr_bucket=width_atr_bucket(w_atr),
        recent_range=rr,
        width_over_recent_range=(width / rr) if rr is not None and rr > 0 else None,
        contributing_swing_count=int(auto.evidence.contributing_swing_count),
        ranking_strength=int(auto.zone.strength),
        departure_move=auto.evidence.departure_move,
        cluster_tolerance=float(auto.evidence.cluster_tolerance),
        origin_swing_price=origin["origin_swing_price"],
        origin_bar_range=origin["origin_bar_range"],
        origin_to_zone_mid=origin["origin_to_zone_mid"],
        prior_opposite_swing_distance=origin["prior_opposite_swing_distance"],
    )


def compute_lifecycle(
    auto: AutomaticZone,
    evaluation: ZoneEvaluation | None,
) -> ZoneLifecycleFeatures:
    conf_i = auto.evidence.origin_confirmation_index
    interactions = () if evaluation is None else evaluation.interactions
    if not interactions:
        return ZoneLifecycleFeatures(
            zone_id=auto.zone.id,
            interaction_count=0,
            age_bars_to_first_interaction=None,
            age_bucket_first_interaction=age_bars_bucket(None),
            interactions_before_first_decisive=None,
            first_outcome=None,
            prior_touches_before_decisive=None,
        )

    first = interactions[0]
    age = int(first.entry_index - conf_i)
    first_decisive = None
    for ix in interactions:
        if ix.outcome in (
            InteractionOutcome.SUCCESS,
            InteractionOutcome.FAILURE,
            InteractionOutcome.BROKEN,
        ):
            first_decisive = ix
            break
    return ZoneLifecycleFeatures(
        zone_id=auto.zone.id,
        interaction_count=len(interactions),
        age_bars_to_first_interaction=age,
        age_bucket_first_interaction=age_bars_bucket(age),
        interactions_before_first_decisive=(
            None if first_decisive is None else int(first_decisive.interaction_index)
        ),
        first_outcome=None if first_decisive is None else first_decisive.outcome.value,
        prior_touches_before_decisive=(
            None if first_decisive is None else int(first_decisive.interaction_index)
        ),
    )


def compute_interaction_geometry(
    auto: AutomaticZone,
    interaction: ZoneInteractionEvaluation,
    bars: Sequence[Bar],
) -> InteractionGeometryFeatures:
    conf_i = auto.evidence.origin_confirmation_index
    bar = bars[interaction.entry_index]
    atr = interaction.atr_at_interaction
    pen = penetration_at_entry(auto.zone.low, auto.zone.high, auto.zone.kind, bar)
    return InteractionGeometryFeatures(
        zone_id=auto.zone.id,
        interaction_index=int(interaction.interaction_index),
        entry_index=int(interaction.entry_index),
        age_bars_at_interaction=int(interaction.entry_index - conf_i),
        prior_touches=int(interaction.interaction_index),
        outcome=interaction.outcome.value,
        break_detected=bool(interaction.break_detected),
        atr_at_interaction=atr,
        mfe=interaction.mfe,
        mae=interaction.mae,
        mfe_over_atr=(
            None
            if atr is None or atr <= 0 or interaction.mfe is None
            else float(interaction.mfe) / atr
        ),
        mae_over_atr=(
            None
            if atr is None or atr <= 0 or interaction.mae is None
            else float(interaction.mae) / atr
        ),
        penetration=pen,
    )


def _outcome_totals(
    evaluations: Sequence[ZoneEvaluation],
    zone_ids: set[int] | None = None,
) -> dict[str, Any]:
    selected = [
        e
        for e in evaluations
        if zone_ids is None or e.zone_id in zone_ids
    ]
    success = sum(e.successful_reaction_count for e in selected)
    failure = sum(e.failed_reaction_count for e in selected)
    broken = sum(e.broken_count for e in selected)
    unavailable = sum(e.unavailable_count for e in selected)
    interactions = sum(e.sample_count for e in selected)
    decisive = success + failure + broken
    return {
        "zone_count": len({e.zone_id for e in selected}),
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


def _bucket_report(
    *,
    bucket_name: str,
    zone_ids: set[int],
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    creations: Mapping[int, ZoneCreationGeometry],
    lifecycles: Mapping[int, ZoneLifecycleFeatures],
) -> dict[str, Any]:
    selected_zones = [z for z in zones if z.zone.id in zone_ids]
    outcomes = _outcome_totals(evaluations, zone_ids)
    widths = [creations[z.zone.id].absolute_width for z in selected_zones if z.zone.id in creations]
    w_atrs = [
        creations[z.zone.id].width_over_atr
        for z in selected_zones
        if z.zone.id in creations and creations[z.zone.id].width_over_atr is not None
    ]
    ages = [
        lifecycles[z.zone.id].age_bars_to_first_interaction
        for z in selected_zones
        if z.zone.id in lifecycles
        and lifecycles[z.zone.id].age_bars_to_first_interaction is not None
    ]
    touches = [
        float(lifecycles[z.zone.id].interaction_count)
        for z in selected_zones
        if z.zone.id in lifecycles
    ]
    eval_by_id = {e.zone_id: e for e in evaluations}
    mfes = [
        e.median_mfe
        for zid in zone_ids
        if (e := eval_by_id.get(zid)) is not None and e.median_mfe is not None
    ]
    maes = [
        e.median_mae
        for zid in zone_ids
        if (e := eval_by_id.get(zid)) is not None and e.median_mae is not None
    ]
    too_small = (
        outcomes["zone_count"] < MIN_INTERPRETABLE_ZONES
        or outcomes["interaction_count"] < MIN_INTERPRETABLE_INTERACTIONS
    )
    return {
        "bucket": bucket_name,
        **outcomes,
        "average_zone_width": mean(widths) if widths else None,
        "median_zone_width": median(widths) if widths else None,
        "average_width_over_atr": mean(w_atrs) if w_atrs else None,  # type: ignore[arg-type]
        "median_width_over_atr": median(w_atrs) if w_atrs else None,  # type: ignore[arg-type]
        "average_age_bars_to_first_interaction": mean(ages) if ages else None,  # type: ignore[arg-type]
        "median_age_bars_to_first_interaction": median(ages) if ages else None,  # type: ignore[arg-type]
        "average_interactions": mean(touches) if touches else None,
        "median_interactions": median(touches) if touches else None,
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
        "sample_size": {
            "zones": outcomes["zone_count"],
            "interactions": outcomes["interaction_count"],
            "min_zones_for_interpretation": MIN_INTERPRETABLE_ZONES,
            "min_interactions_for_interpretation": MIN_INTERPRETABLE_INTERACTIONS,
            "too_small_to_interpret": too_small,
        },
        "disclaimer": (
            "zone_eval_v1 outcomes stratified by geometry/lifecycle — "
            "not predictive accuracy."
        ),
    }


def _interaction_bucket_report(
    *,
    bucket_name: str,
    interactions: Sequence[InteractionGeometryFeatures],
) -> dict[str, Any]:
    success = sum(1 for i in interactions if i.outcome == InteractionOutcome.SUCCESS.value)
    failure = sum(1 for i in interactions if i.outcome == InteractionOutcome.FAILURE.value)
    broken = sum(1 for i in interactions if i.outcome == InteractionOutcome.BROKEN.value)
    unavailable = sum(
        1 for i in interactions if i.outcome == InteractionOutcome.UNAVAILABLE.value
    )
    decisive = success + failure + broken
    depths = [
        i.penetration["wick_depth_over_width"]
        for i in interactions
        if i.penetration.get("wick_depth_over_width") is not None
    ]
    mfes = [i.mfe for i in interactions if i.mfe is not None]
    maes = [i.mae for i in interactions if i.mae is not None]
    ages = [float(i.age_bars_at_interaction) for i in interactions]
    too_small = len(interactions) < MIN_INTERPRETABLE_INTERACTIONS
    return {
        "bucket": bucket_name,
        "interaction_count": len(interactions),
        "SUCCESS_count": success,
        "FAILURE_count": failure,
        "BROKEN_count": broken,
        "UNAVAILABLE_count": unavailable,
        "success_rate": _safe_rate(success, decisive),
        "failure_rate": _safe_rate(failure, decisive),
        "broken_rate": _safe_rate(broken, decisive),
        "average_age_bars": mean(ages) if ages else None,
        "median_age_bars": median(ages) if ages else None,
        "median_wick_depth_over_width": median(depths) if depths else None,  # type: ignore[arg-type]
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
        "close_through_count": sum(
            1 for i in interactions if i.penetration.get("close_through")
        ),
        "wick_only_count": sum(
            1 for i in interactions if i.penetration.get("wick_only_penetration")
        ),
        "sample_size": {
            "interactions": len(interactions),
            "min_interactions_for_interpretation": MIN_INTERPRETABLE_INTERACTIONS,
            "too_small_to_interpret": too_small,
        },
    }


def diagnose_geometry_lifecycle(
    *,
    by_width_atr: Mapping[str, Any],
    by_age: Mapping[str, Any],
    by_kind: Mapping[str, Any],
) -> dict[str, Any]:
    """Answer whether geometry/lifecycle justifies ONE controlled Zone V1 experiment."""
    notes: list[str] = []
    candidates: list[dict[str, Any]] = []

    def _consider(group: str, buckets: Mapping[str, Any]) -> None:
        interpretable = [
            (name, metrics)
            for name, metrics in buckets.items()
            if not metrics.get("sample_size", {}).get("too_small_to_interpret", True)
            and metrics.get("broken_rate") is not None
        ]
        if len(interpretable) < 2:
            notes.append(f"{group}: fewer than 2 interpretable buckets")
            return
        broken_rates = [(n, float(m["broken_rate"])) for n, m in interpretable]
        lo = min(broken_rates, key=lambda x: x[1])
        hi = max(broken_rates, key=lambda x: x[1])
        gap = hi[1] - lo[1]
        notes.append(
            f"{group}: broken low={lo[0]}:{lo[1]:.4f} high={hi[0]}:{hi[1]:.4f} gap={gap:.4f}"
        )
        if gap >= MATERIAL_GAP:
            candidates.append(
                {
                    "dimension": group,
                    "low_broken_bucket": lo[0],
                    "low_broken_rate": lo[1],
                    "high_broken_bucket": hi[0],
                    "high_broken_rate": hi[1],
                    "gap": gap,
                }
            )

    _consider("width_over_atr", by_width_atr)
    _consider("age_to_first_interaction", by_age)
    _consider("zone_kind", by_kind)

    if not candidates:
        # Check if all interpretable buckets still show high broken (~baseline).
        all_rates = []
        for block in (by_width_atr, by_age, by_kind):
            for metrics in block.values():
                if (
                    not metrics.get("sample_size", {}).get("too_small_to_interpret", True)
                    and metrics.get("broken_rate") is not None
                ):
                    all_rates.append(float(metrics["broken_rate"]))
        if not all_rates:
            code = "INCONCLUSIVE_SAMPLE"
            answer = (
                "No — sample sizes are too small to justify a geometry/lifecycle "
                "Zone V1 experiment."
            )
        else:
            code = "GEOMETRY_LIFECYCLE_DOES_NOT_EXPLAIN_ENOUGH"
            answer = (
                "No — measurable geometry/lifecycle buckets do not show a strong, "
                "stable association with broken rates (gap below diagnostic "
                f"threshold {MATERIAL_GAP}). The high broken rate appears broadly "
                "shared across width/ATR, age, and supply/demand. "
                "Next most informative diagnostic: interaction/break mechanics "
                "(close-through vs wick, penetration depth distribution vs "
                "outcome) with fixed evaluator semantics, or zone-bound "
                "construction rules inspected qualitatively — still without "
                "tuning thresholds to chase success rate."
            )
    else:
        best = max(candidates, key=lambda c: c["gap"])
        code = "GEOMETRY_LIFECYCLE_APPEARS_MATERIAL"
        answer = (
            "Yes — a geometry/lifecycle dimension shows a material broken-rate "
            f"gap (best: {best['dimension']} "
            f"{best['low_broken_bucket']}={best['low_broken_rate']:.3f} vs "
            f"{best['high_broken_bucket']}={best['high_broken_rate']:.3f}). "
            "This may justify ONE controlled Zone V1 experiment on that "
            "dimension only. Not predictive accuracy; do not auto-optimize."
        )
        notes.append(f"leading_candidate={best}")

    return {
        "conclusion_code": code,
        "answers_research_question": answer,
        "research_question": (
            "Is the high broken-zone rate plausibly associated with a measurable "
            "zone geometry or lifecycle characteristic that is strong and stable "
            "enough to justify ONE controlled Zone V1 experiment?"
        ),
        "material_gap_threshold": MATERIAL_GAP,
        "candidates": candidates,
        "notes": notes,
        "disclaimer": (
            "Diagnostic stratification only. Zone Evaluation V1 outcomes "
            "unchanged. Do not modify Zone V1 from this report alone."
        ),
    }


@dataclass(frozen=True)
class GeometryLifecycleExperimentResult:
    timeframe: str
    window_start: str | None
    window_end: str | None
    baseline: dict[str, Any]
    creations: tuple[ZoneCreationGeometry, ...]
    lifecycles: tuple[ZoneLifecycleFeatures, ...]
    interactions: tuple[InteractionGeometryFeatures, ...]
    aggregates: dict[str, Any]
    diagnosis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "timeframe": self.timeframe,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "baseline": self.baseline,
            "creation_count": len(self.creations),
            "interaction_feature_count": len(self.interactions),
            "creations": [c.to_dict() for c in self.creations],
            "lifecycles": [c.to_dict() for c in self.lifecycles],
            "interaction_features": [i.to_dict() for i in self.interactions],
            "aggregates": self.aggregates,
            "diagnosis": self.diagnosis,
            "disclaimer": (
                "Creation-time vs interaction-time features are separated. "
                "Rates are zone_eval_v1 outcomes, not predictive accuracy."
            ),
        }


def run_geometry_lifecycle_on_zones(
    zones: Sequence[AutomaticZone],
    evaluations: Sequence[ZoneEvaluation],
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str = "M15",
    window_start: date | str | None = None,
    window_end: date | str | None = None,
    include_detail_rows: bool = True,
) -> GeometryLifecycleExperimentResult:
    eval_by_id = {e.zone_id: e for e in evaluations}
    creations: list[ZoneCreationGeometry] = []
    lifecycles: list[ZoneLifecycleFeatures] = []
    interactions: list[InteractionGeometryFeatures] = []

    for auto in zones:
        creation = compute_creation_geometry(
            auto, bars, symbol=symbol, timeframe=timeframe
        )
        creations.append(creation)
        ev = eval_by_id.get(auto.zone.id)
        life = compute_lifecycle(auto, ev)
        lifecycles.append(life)
        if ev is not None:
            for ix in ev.interactions:
                interactions.append(compute_interaction_geometry(auto, ix, bars))

    creation_by_id = {c.zone_id: c for c in creations}
    life_by_id = {c.zone_id: c for c in lifecycles}

    baseline = _outcome_totals(evaluations)
    baseline["absolute_width_distribution"] = _distribution(
        [c.absolute_width for c in creations]
    )
    baseline["width_over_atr_distribution"] = _distribution(
        [c.width_over_atr for c in creations if c.width_over_atr is not None]
    )
    baseline["age_to_first_interaction_distribution"] = _distribution(
        [
            float(c.age_bars_to_first_interaction)
            for c in lifecycles
            if c.age_bars_to_first_interaction is not None
        ]
    )

    # Geometry buckets
    by_width_atr: dict[str, Any] = {}
    for label, _, _ in WIDTH_ATR_BUCKETS:
        ids = {c.zone_id for c in creations if c.width_atr_bucket == label}
        by_width_atr[label] = _bucket_report(
            bucket_name=label,
            zone_ids=ids,
            zones=zones,
            evaluations=evaluations,
            creations=creation_by_id,
            lifecycles=life_by_id,
        )

    by_age: dict[str, Any] = {}
    for label, _, _ in AGE_BUCKETS_BARS:
        ids = {
            c.zone_id
            for c in lifecycles
            if c.age_bucket_first_interaction == label
        }
        by_age[label] = _bucket_report(
            bucket_name=label,
            zone_ids=ids,
            zones=zones,
            evaluations=evaluations,
            creations=creation_by_id,
            lifecycles=life_by_id,
        )

    by_kind: dict[str, Any] = {}
    for kind in ("supply", "demand", "unknown"):
        if kind == "unknown":
            ids = {c.zone_id for c in creations if c.zone_kind is None}
        else:
            ids = {c.zone_id for c in creations if c.zone_kind == kind}
        by_kind[kind] = _bucket_report(
            bucket_name=kind,
            zone_ids=ids,
            zones=zones,
            evaluations=evaluations,
            creations=creation_by_id,
            lifecycles=life_by_id,
        )

    # Interaction-time buckets
    by_prior_touches: dict[str, Any] = {}
    for label in TOUCH_BUCKETS:
        subset = [i for i in interactions if touch_bucket(i.prior_touches) == label]
        by_prior_touches[label] = _interaction_bucket_report(
            bucket_name=label, interactions=subset
        )

    by_close_through = {
        "close_through": _interaction_bucket_report(
            bucket_name="close_through",
            interactions=[
                i for i in interactions if i.penetration.get("close_through")
            ],
        ),
        "wick_only": _interaction_bucket_report(
            bucket_name="wick_only",
            interactions=[
                i for i in interactions if i.penetration.get("wick_only_penetration")
            ],
        ),
        "close_inside": _interaction_bucket_report(
            bucket_name="close_inside",
            interactions=[
                i
                for i in interactions
                if i.penetration.get("close_inside")
                and not i.penetration.get("close_through")
            ],
        ),
    }

    # Continuous: width/ATR of zones that saw broken vs success interactions
    any_broken = {
        i.zone_id for i in interactions if i.outcome == InteractionOutcome.BROKEN.value
    }
    any_success = {
        i.zone_id for i in interactions if i.outcome == InteractionOutcome.SUCCESS.value
    }
    continuous = {
        "width_over_atr_all": _distribution(
            [c.width_over_atr for c in creations if c.width_over_atr is not None]
        ),
        "width_over_atr_zones_with_broken": _distribution(
            [
                creation_by_id[zid].width_over_atr
                for zid in any_broken
                if zid in creation_by_id and creation_by_id[zid].width_over_atr is not None
            ]
        ),
        "width_over_atr_zones_with_success": _distribution(
            [
                creation_by_id[zid].width_over_atr
                for zid in any_success
                if zid in creation_by_id and creation_by_id[zid].width_over_atr is not None
            ]
        ),
        "wick_depth_over_width_by_outcome": {
            outcome: _distribution(
                [
                    float(i.penetration["wick_depth_over_width"])
                    for i in interactions
                    if i.outcome == outcome
                    and i.penetration.get("wick_depth_over_width") is not None
                ]
            )
            for outcome in (
                InteractionOutcome.SUCCESS.value,
                InteractionOutcome.FAILURE.value,
                InteractionOutcome.BROKEN.value,
                InteractionOutcome.UNAVAILABLE.value,
            )
        },
    }

    aggregates = {
        "by_width_over_atr": by_width_atr,
        "by_age_to_first_interaction": by_age,
        "by_zone_kind": by_kind,
        "by_prior_touches_at_interaction": by_prior_touches,
        "by_penetration_style": by_close_through,
        "continuous_distributions": continuous,
        "too_small_width_atr_buckets": [
            k
            for k, v in by_width_atr.items()
            if v["sample_size"]["too_small_to_interpret"]
        ],
        "too_small_age_buckets": [
            k for k, v in by_age.items() if v["sample_size"]["too_small_to_interpret"]
        ],
        "interpretable_width_atr_buckets": [
            k
            for k, v in by_width_atr.items()
            if not v["sample_size"]["too_small_to_interpret"]
        ],
        "interpretable_age_buckets": [
            k
            for k, v in by_age.items()
            if not v["sample_size"]["too_small_to_interpret"]
        ],
    }

    diagnosis = diagnose_geometry_lifecycle(
        by_width_atr=by_width_atr,
        by_age=by_age,
        by_kind=by_kind,
    )

    return GeometryLifecycleExperimentResult(
        timeframe=timeframe,
        window_start=None if window_start is None else str(window_start),
        window_end=None if window_end is None else str(window_end),
        baseline=baseline,
        creations=tuple(creations) if include_detail_rows else (),
        lifecycles=tuple(lifecycles) if include_detail_rows else (),
        interactions=tuple(interactions) if include_detail_rows else (),
        aggregates=aggregates,
        diagnosis=diagnosis,
    )
