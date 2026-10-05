"""Controlled experiment: V1_WIDTH_FILTER vs baseline Automatic Zone V1.

Baseline generation uses unchanged ``AutomaticZoneGenerator`` /
``SwingClusterZoneGeneratorV1``. The experiment applies a single
creation-time eligibility rule: retain zones only when

    (zone.high - zone.low) / causal_ATR(origin_confirmation_index) >= threshold

Zone Evaluation V1 is unchanged. Does not modify live trading paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from core.zones import (
    METHOD_SWING_CLUSTER_ZONE_V1,
    METHOD_ZONE_EVAL_V1,
    AutomaticZone,
    ZoneEvaluation,
    ZoneEvaluationConfig,
    ZoneEvaluator,
)
from core.zones.auto.atr import causal_atr
from models.bar import Bar
from research.zones_pipeline import (
    resolve_evaluation_window,
    run_timeframe_pipeline,
    split_date_range_into_thirds,
)
from research.free_ohlc.dataset import build_research_dataset

EXPERIMENT_VERSION = "width_filter_v1_experiment_v1"
VARIANT_ID = "V1_WIDTH_FILTER"
BASELINE_LABEL = "baseline_v1"
EXPERIMENT_LABEL = "v1_width_filter"

# ---------------------------------------------------------------------------
# PREDECLARED THRESHOLD (fixed before examining experimental outcomes)
# ---------------------------------------------------------------------------
# Rationale (registered before running the experiment):
# - Diagnostic median width/ATR ≈ 0.12; bucket boundary at 0.5 is NOT used as
#   the filter cut (that would be outcome-guided).
# - 0.35 requires band width ≥ 35% of causal ATR at zone creation — a single,
#   moderate exclusion of the narrowest bands without adopting the diagnostic
#   bucket edge.
# - Expected to retain more coverage than 0.5 while still testing whether
#   excessively narrow V1 bands drive the high broken rate.
PREDECLARED_MIN_WIDTH_ATR_RATIO = 0.35
DEFAULT_ATR_PERIOD = 14

# Coverage heuristics for interpretation (not trading gates).
SUBSTANTIAL_ZONE_RETENTION = 0.40
SUBSTANTIAL_INTERACTION_RETENTION = 0.40
MEANINGFUL_BROKEN_DELTA = 0.03
THIRD_STABILITY_MAX_SPREAD = 0.08


@dataclass(frozen=True)
class WidthFilterExperimentConfig:
    """Explicit experimental variant configuration."""

    min_width_atr_ratio: float = PREDECLARED_MIN_WIDTH_ATR_RATIO
    atr_period: int = DEFAULT_ATR_PERIOD
    variant_id: str = VARIANT_ID
    baseline_method_id: str = METHOD_SWING_CLUSTER_ZONE_V1

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "min_width_atr_ratio": self.min_width_atr_ratio,
            "atr_period": self.atr_period,
            "baseline_method_id": self.baseline_method_id,
            "threshold_rationale": (
                "Predeclared at 0.35 — above typical V1 median width/ATR (~0.12) "
                "but below the diagnostic 0.5 bucket boundary; not outcome-tuned."
            ),
        }


def zone_absolute_width(auto: AutomaticZone) -> float:
    return float(auto.zone.high - auto.zone.low)


def zone_width_atr_ratio(
    auto: AutomaticZone,
    bars: Sequence[Bar],
    *,
    atr_period: int = DEFAULT_ATR_PERIOD,
) -> float | None:
    """Width / causal ATR at origin confirmation — creation-time only."""
    conf_i = auto.evidence.origin_confirmation_index
    if conf_i < 0 or conf_i >= len(bars):
        return None
    width = zone_absolute_width(auto)
    atr = causal_atr(bars, asof_index=conf_i, period=atr_period)
    if atr is None or atr <= 0:
        return None
    return width / atr


def passes_width_filter(
    auto: AutomaticZone,
    bars: Sequence[Bar],
    *,
    min_width_atr_ratio: float,
    atr_period: int = DEFAULT_ATR_PERIOD,
) -> bool:
    """True when zone meets minimum width/ATR at creation (>= threshold)."""
    ratio = zone_width_atr_ratio(auto, bars, atr_period=atr_period)
    if ratio is None:
        return False
    return ratio >= min_width_atr_ratio


def apply_width_filter(
    zones: Sequence[AutomaticZone],
    bars: Sequence[Bar],
    *,
    config: WidthFilterExperimentConfig | None = None,
) -> tuple[tuple[AutomaticZone, ...], tuple[AutomaticZone, ...]]:
    """Split V1 zones into retained (experiment) and rejected without mutating V1."""
    cfg = config or WidthFilterExperimentConfig()
    retained: list[AutomaticZone] = []
    rejected: list[AutomaticZone] = []
    for auto in zones:
        if passes_width_filter(
            auto,
            bars,
            min_width_atr_ratio=cfg.min_width_atr_ratio,
            atr_period=cfg.atr_period,
        ):
            retained.append(auto)
        else:
            rejected.append(auto)
    return tuple(retained), tuple(rejected)


def _safe_rate(num: int, den: int) -> float | None:
    return (num / den) if den else None


def _outcome_metrics(
    evaluations: Sequence[ZoneEvaluation],
    *,
    zones: Sequence[AutomaticZone],
    bars: Sequence[Bar],
    config: WidthFilterExperimentConfig,
) -> dict[str, Any]:
    success = sum(e.successful_reaction_count for e in evaluations)
    failure = sum(e.failed_reaction_count for e in evaluations)
    broken = sum(e.broken_count for e in evaluations)
    unavailable = sum(e.unavailable_count for e in evaluations)
    interactions = sum(e.sample_count for e in evaluations)
    decisive = success + failure + broken

    ratios = [
        r
        for z in zones
        if (r := zone_width_atr_ratio(z, bars, atr_period=config.atr_period))
        is not None
    ]
    mfes = [e.median_mfe for e in evaluations if e.median_mfe is not None]
    maes = [e.median_mae for e in evaluations if e.median_mae is not None]

    return {
        "total_zones": len(zones),
        "total_interactions": interactions,
        "SUCCESS_count": success,
        "FAILURE_count": failure,
        "BROKEN_count": broken,
        "UNAVAILABLE_count": unavailable,
        "success_rate": _safe_rate(success, decisive),
        "failure_rate": _safe_rate(failure, decisive),
        "broken_rate": _safe_rate(broken, decisive),
        "unavailable_rate": _safe_rate(unavailable, interactions),
        "median_width_atr": median(ratios) if ratios else None,
        "median_mfe": median(mfes) if mfes else None,
        "median_mae": median(maes) if maes else None,
    }


def _retention_metrics(
    baseline: dict[str, Any],
    experiment: dict[str, Any],
    *,
    baseline_zones: int,
    experiment_zones: int,
    rejected_zones: int,
) -> dict[str, Any]:
    b_ix = int(baseline["total_interactions"])
    e_ix = int(experiment["total_interactions"])
    return {
        "zones_retained": experiment_zones,
        "zones_rejected_by_width_filter": rejected_zones,
        "zone_retention_pct": (
            (experiment_zones / baseline_zones) if baseline_zones else None
        ),
        "interaction_retention_pct": ((e_ix / b_ix) if b_ix else None),
        "interaction_coverage": e_ix,
        "baseline_interactions": b_ix,
    }


def evaluate_variant(
    zones: Sequence[AutomaticZone],
    bars: Sequence[Bar],
    *,
    symbol: str,
    config: WidthFilterExperimentConfig | None = None,
    asof_index: int | None = None,
) -> tuple[tuple[ZoneEvaluation, ...], dict[str, Any]]:
    """Evaluate zones with unchanged Zone Evaluation V1."""
    cfg = config or WidthFilterExperimentConfig()
    resolved_asof = len(bars) - 1 if asof_index is None else asof_index
    evaluator = ZoneEvaluator(ZoneEvaluationConfig())
    evaluations = evaluator.evaluate(zones, bars, asof_index=resolved_asof)
    metrics = _outcome_metrics(evaluations, zones=zones, bars=bars, config=cfg)
    return evaluations, metrics


def run_single_window_comparison(
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str = "M15",
    config: WidthFilterExperimentConfig | None = None,
    asof_index: int | None = None,
) -> dict[str, Any]:
    """Run baseline V1 + width-filter experiment on one bar window."""
    cfg = config or WidthFilterExperimentConfig()

    baseline_zones, baseline_evals, _ = run_timeframe_pipeline(
        bars,
        timeframe=timeframe,
        symbol=symbol,
        asof_index=asof_index,
    )
    baseline_metrics = _outcome_metrics(
        baseline_evals, zones=baseline_zones, bars=bars, config=cfg
    )

    experiment_zones, rejected_zones = apply_width_filter(
        baseline_zones, bars, config=cfg
    )
    experiment_evals, experiment_metrics = evaluate_variant(
        experiment_zones,
        bars,
        symbol=symbol,
        config=cfg,
        asof_index=asof_index,
    )

    retention = _retention_metrics(
        baseline_metrics,
        experiment_metrics,
        baseline_zones=len(baseline_zones),
        experiment_zones=len(experiment_zones),
        rejected_zones=len(rejected_zones),
    )

    return {
        "baseline": {
            "label": BASELINE_LABEL,
            "method_id": cfg.baseline_method_id,
            **baseline_metrics,
        },
        "experiment": {
            "label": EXPERIMENT_LABEL,
            "variant_id": cfg.variant_id,
            "filter_config": cfg.to_dict(),
            **experiment_metrics,
            **retention,
        },
        "comparison": {
            "broken_rate_delta": (
                None
                if baseline_metrics["broken_rate"] is None
                or experiment_metrics["broken_rate"] is None
                else experiment_metrics["broken_rate"]
                - baseline_metrics["broken_rate"]
            ),
            "success_rate_delta": (
                None
                if baseline_metrics["success_rate"] is None
                or experiment_metrics["success_rate"] is None
                else experiment_metrics["success_rate"]
                - baseline_metrics["success_rate"]
            ),
            "median_width_atr_delta": (
                None
                if baseline_metrics["median_width_atr"] is None
                or experiment_metrics["median_width_atr"] is None
                else experiment_metrics["median_width_atr"]
                - baseline_metrics["median_width_atr"]
            ),
        },
    }


def classify_experiment_outcome(
    full_window: dict[str, Any],
    thirds: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Classify A/B/C/D — trade-off of outcomes vs coverage vs stability."""
    base_br = full_window["baseline"]["broken_rate"]
    exp_br = full_window["experiment"]["broken_rate"]
    zone_ret = full_window["experiment"].get("zone_retention_pct")
    ix_ret = full_window["experiment"].get("interaction_retention_pct")
    broken_improved = (
        base_br is not None
        and exp_br is not None
        and (base_br - exp_br) >= MEANINGFUL_BROKEN_DELTA
    )
    substantial_coverage = (
        zone_ret is not None
        and ix_ret is not None
        and zone_ret >= SUBSTANTIAL_ZONE_RETENTION
        and ix_ret >= SUBSTANTIAL_INTERACTION_RETENTION
    )

    third_deltas: list[float] = []
    for row in thirds:
        comp = row.get("comparison", {})
        delta = comp.get("broken_rate_delta")
        if delta is not None:
            third_deltas.append(float(delta))
    spread = (max(third_deltas) - min(third_deltas)) if len(third_deltas) >= 2 else None
    stable = spread is not None and spread <= THIRD_STABILITY_MAX_SPREAD

    if not broken_improved:
        code = "C_NO_MEANINGFUL_IMPROVEMENT"
        answer = (
            "No — the minimum width/causal-ATR filter does not produce a stable, "
            "practically meaningful improvement over Zone V1 when weighing outcome "
            "quality and coverage. Broken rate did not improve meaningfully."
        )
    elif broken_improved and not substantial_coverage:
        code = "B_IMPROVES_BUT_DESTROYS_COVERAGE"
        answer = (
            "No for practical adoption — broken rate improved but zone/interaction "
            "retention fell below substantial coverage thresholds. Not a stable "
            "practical improvement over baseline V1."
        )
    elif broken_improved and substantial_coverage and not stable:
        code = "D_UNSTABLE_IMPROVEMENT"
        answer = (
            "No — broken rate improved with adequate full-window retention, but "
            "improvement is unstable across chronological thirds."
        )
    else:
        code = "A_IMPROVES_WITH_SUBSTANTIAL_COVERAGE"
        answer = (
            "Yes — the filter improves broken-rate outcomes while retaining "
            "substantial zone and interaction coverage, with stable direction "
            "across thirds. This is evidence for ONE controlled V1 change — "
            "not predictive accuracy. Do not proceed to further optimization."
        )

    return {
        "classification_code": code,
        "answers_research_question": answer,
        "research_question": (
            "Does the minimum zone-width / causal-ATR filter produce a stable "
            "and practically meaningful improvement over Zone V1, considering "
            "both outcome quality AND coverage?"
        ),
        "broken_improved": broken_improved,
        "substantial_coverage": substantial_coverage,
        "stable_across_thirds": stable,
        "third_broken_rate_delta_spread": spread,
        "thresholds": {
            "meaningful_broken_delta": MEANINGFUL_BROKEN_DELTA,
            "substantial_zone_retention": SUBSTANTIAL_ZONE_RETENTION,
            "substantial_interaction_retention": SUBSTANTIAL_INTERACTION_RETENTION,
            "third_stability_max_spread": THIRD_STABILITY_MAX_SPREAD,
        },
        "disclaimer": (
            "Lower broken rate alone is not 'better'. Evaluate trade-off with "
            "retention and third stability. zone_eval_v1 outcomes unchanged."
        ),
    }


@dataclass(frozen=True)
class WidthFilterExperimentResult:
    source_path: str
    symbol: str
    effective_start: str | None
    effective_end: str | None
    timeframe: str
    config: WidthFilterExperimentConfig
    full_window: dict[str, Any]
    chronological_thirds: tuple[dict[str, Any], ...]
    classification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "evaluation_method_id": METHOD_ZONE_EVAL_V1,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "timeframe": self.timeframe,
            "config": self.config.to_dict(),
            "full_window": self.full_window,
            "chronological_thirds": list(self.chronological_thirds),
            "classification": self.classification,
            "disclaimer": (
                "Baseline uses unchanged Automatic Zone V1. Experiment applies "
                "creation-time width/ATR eligibility only. Not predictive accuracy."
            ),
        }


def run_width_filter_experiment(
    csv_path: Path | str,
    *,
    symbol: str = "EURUSD",
    start: date | None = None,
    end: date | None = None,
    timeframe: str = "M15",
    config: WidthFilterExperimentConfig | None = None,
    skip_invalid_ohlc: bool = True,
) -> WidthFilterExperimentResult:
    """Full dataset + chronological thirds: baseline vs V1_WIDTH_FILTER."""
    path = Path(csv_path)
    cfg = config or WidthFilterExperimentConfig()
    tf = timeframe.strip().upper()

    _, effective_start, effective_end = resolve_evaluation_window(
        path,
        symbol=symbol,
        start=start,
        end=end,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )

    dataset = build_research_dataset(
        path,
        symbol=symbol,
        start=effective_start,
        end=effective_end,
        skip_invalid_ohlc=skip_invalid_ohlc,
        target_timeframes=(tf,),
    )
    bars = dataset.bars(tf)

    full = run_single_window_comparison(
        bars, symbol=symbol, timeframe=tf, config=cfg
    )

    thirds_rows: list[dict[str, Any]] = []
    if effective_start is not None and effective_end is not None:
        for label, seg_start, seg_end in split_date_range_into_thirds(
            effective_start, effective_end
        ):
            seg_ds = build_research_dataset(
                path,
                symbol=symbol,
                start=seg_start,
                end=seg_end,
                skip_invalid_ohlc=skip_invalid_ohlc,
                target_timeframes=(tf,),
            )
            seg_bars = seg_ds.bars(tf)
            if not seg_bars:
                thirds_rows.append(
                    {
                        "label": label,
                        "start": seg_start.isoformat(),
                        "end": seg_end.isoformat(),
                        "baseline": {"total_zones": 0, "total_interactions": 0},
                        "experiment": {"total_zones": 0, "zones_rejected_by_width_filter": 0},
                    }
                )
                continue
            row = run_single_window_comparison(
                seg_bars, symbol=symbol, timeframe=tf, config=cfg
            )
            thirds_rows.append(
                {
                    "label": label,
                    "start": seg_start.isoformat(),
                    "end": seg_end.isoformat(),
                    **row,
                }
            )

    classification = classify_experiment_outcome(full, thirds_rows)

    return WidthFilterExperimentResult(
        source_path=str(path),
        symbol=symbol.strip().upper(),
        effective_start=effective_start.isoformat() if effective_start else None,
        effective_end=effective_end.isoformat() if effective_end else None,
        timeframe=tf,
        config=cfg,
        full_window=full,
        chronological_thirds=tuple(thirds_rows),
        classification=classification,
    )
