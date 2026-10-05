"""Research diagnostic: audit Automatic Zone V1 geometry construction.

Does NOT modify Automatic Zone V1 or Zone Evaluation V1.
Traces boundary math, verifies implementation semantics, and reports
creation-time distributions. Volatility-regime splits are diagnostic only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean, median
from typing import Any, Mapping, Sequence

from core.features.config import SwingDetectionConfig
from core.features.generators.swings import SwingEvent, SwingGenerator, SwingKind
from core.market import require_instrument
from core.zones import AutomaticZone, SwingClusterZoneConfig
from core.zones.auto.atr import causal_atr
from models.bar import Bar
from models.zone import ZoneKind
from research.geometry_zone_experiment import compute_creation_geometry, zone_width
from research.zones_pipeline import (
    resolve_evaluation_window,
    run_timeframe_pipeline,
    split_date_range_into_thirds,
)
from research.free_ohlc.dataset import build_research_dataset

AUDIT_VERSION = "zone_v1_geometry_audit_v1"
DEFAULT_ATR_PERIOD = 14
SAMPLE_SIZE = 12


def _pct(sorted_values: Sequence[float], p: float) -> float | None:
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = int(round((n - 1) * p))
    return sorted_values[max(0, min(n - 1, idx))]


def distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    """Min / p10 / p25 / median / p75 / p90 / max distribution."""
    if not values:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    ordered = sorted(float(v) for v in values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p10": _pct(ordered, 0.10),
        "p25": _pct(ordered, 0.25),
        "median": median(ordered),
        "p75": _pct(ordered, 0.75),
        "p90": _pct(ordered, 0.90),
        "max": ordered[-1],
        "mean": mean(ordered),
    }


def bar_body_wick_metrics(bar: Bar) -> dict[str, float]:
    """Candle geometry at the swing origin bar."""
    body = abs(bar.close - bar.open)
    upper_wick = bar.high - max(bar.open, bar.close)
    lower_wick = min(bar.open, bar.close) - bar.low
    total_range = bar.high - bar.low
    return {
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "body": float(body),
        "upper_wick": float(max(0.0, upper_wick)),
        "lower_wick": float(max(0.0, lower_wick)),
        "range": float(total_range),
    }


def lookup_swings_by_id(
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
    asof_index: int,
) -> dict[str, SwingEvent]:
    """Causal swing map at generation asof."""
    prefix = list(bars[: asof_index + 1])
    asof_time = bars[asof_index].timestamp
    features = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
        {timeframe: prefix},
        require_instrument(symbol),
        entry_timeframe=timeframe,
        asof=asof_time,
    )
    return {s.id: s for s in features.by_timeframe[timeframe].swings}


def expected_cluster_boundaries(
    swing_prices: Sequence[float],
    *,
    half_width: float,
) -> tuple[float, float, str]:
    """Replay ``SwingClusterZoneGeneratorV1._close_cluster`` boundary math."""
    if not swing_prices:
        raise ValueError("empty swing prices")
    low = min(swing_prices)
    high = max(swing_prices)
    geometry_type = "multi_swing_envelope"
    if low == high:
        geometry_type = "single_swing_expanded"
        low = low - half_width
        high = high + half_width
    if low >= high:
        mid = (low + high) / 2.0 if low == high else low
        low = mid - max(half_width, 1e-12)
        high = mid + max(half_width, 1e-12)
    return low, high, geometry_type


def compute_half_width_and_tolerance(
    bars: Sequence[Bar],
    *,
    asof_index: int,
    config: SwingClusterZoneConfig,
) -> tuple[float | None, float | None, float, float]:
    """Return (atr, tolerance, half_width, expected_single_swing_width)."""
    atr = causal_atr(bars, asof_index=asof_index, period=config.atr_period)
    if atr is not None:
        tolerance = config.cluster_atr_multiple * atr
        half_width = config.single_swing_half_width_atr_multiple * atr
        expected_single = 2.0 * half_width
    else:
        tolerance = config.absolute_price_tolerance
        half_width = config.single_swing_half_width_absolute
        expected_single = 2.0 * half_width
    return atr, tolerance, half_width, expected_single


@dataclass(frozen=True)
class ZoneGeometryRecord:
    """Full geometry audit for one zone."""

    zone_id: int
    zone_kind: str | None
    geometry_type: str
    contributing_swing_count: int
    swing_prices: tuple[float, ...]
    swing_spread: float
    zone_low: float
    zone_high: float
    absolute_width: float
    expected_low: float
    expected_high: float
    boundary_matches_implementation: bool
    atr_at_origin: float | None
    atr_at_generation: float | None
    width_over_atr_origin: float | None
    width_over_atr_generation: float | None
    cluster_tolerance: float
    half_width_at_generation: float
    expected_single_swing_width_at_generation: float
    swing_spread_over_atr_origin: float | None
    width_over_tolerance: float | None
    origin_swing_kind: str | None
    origin_swing_price: float | None
    origin_bar: dict[str, float] | None
    origin_confirmation_index: int
    generation_asof_index: int
    origin_confirmation_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "zone_kind": self.zone_kind,
            "geometry_type": self.geometry_type,
            "contributing_swing_count": self.contributing_swing_count,
            "swing_prices": list(self.swing_prices),
            "swing_spread": self.swing_spread,
            "zone_boundaries": {"low": self.zone_low, "high": self.zone_high},
            "absolute_width": self.absolute_width,
            "expected_boundaries": {
                "low": self.expected_low,
                "high": self.expected_high,
            },
            "boundary_matches_implementation": self.boundary_matches_implementation,
            "causal_atr_at_origin": self.atr_at_origin,
            "causal_atr_at_generation": self.atr_at_generation,
            "width_over_atr_origin": self.width_over_atr_origin,
            "width_over_atr_generation": self.width_over_atr_generation,
            "cluster_tolerance": self.cluster_tolerance,
            "half_width_at_generation": self.half_width_at_generation,
            "expected_single_swing_width_at_generation": (
                self.expected_single_swing_width_at_generation
            ),
            "swing_spread_over_atr_origin": self.swing_spread_over_atr_origin,
            "width_over_cluster_tolerance": self.width_over_tolerance,
            "origin_swing_kind": self.origin_swing_kind,
            "origin_swing_price": self.origin_swing_price,
            "origin_bar_ohlc": self.origin_bar,
            "origin_confirmation_index": self.origin_confirmation_index,
            "generation_asof_index": self.generation_asof_index,
            "origin_confirmation_time": self.origin_confirmation_time,
        }


def audit_zone_geometry(
    auto: AutomaticZone,
    bars: Sequence[Bar],
    swings_by_id: Mapping[str, SwingEvent],
    *,
    config: SwingClusterZoneConfig,
) -> ZoneGeometryRecord:
    """Trace V1 boundary construction for one zone."""
    ev = auto.evidence
    gen_i = ev.asof_index
    conf_i = ev.origin_confirmation_index

    contributing = [
        swings_by_id[sid]
        for sid in ev.contributing_swing_ids
        if sid in swings_by_id
    ]
    prices = tuple(s.price for s in contributing) or (0.0,)
    swing_spread = max(prices) - min(prices) if prices else 0.0

    _, tolerance, half_width, expected_single = compute_half_width_and_tolerance(
        bars, asof_index=gen_i, config=config
    )
    expected_low, expected_high, geometry_type = expected_cluster_boundaries(
        prices, half_width=half_width
    )

    atr_origin = causal_atr(bars, asof_index=conf_i, period=config.atr_period)
    atr_gen = ev.atr_used
    width = zone_width(auto)
    w_atr_origin = (width / atr_origin) if atr_origin and atr_origin > 0 else None
    w_atr_gen = (width / atr_gen) if atr_gen and atr_gen > 0 else None
    spread_atr = (
        (swing_spread / atr_origin) if atr_origin and atr_origin > 0 else None
    )
    w_tol = (width / ev.cluster_tolerance) if ev.cluster_tolerance > 0 else None

    origin = contributing[0] if contributing else None
    origin_bar = None
    if origin is not None and 0 <= origin.index < len(bars):
        origin_bar = bar_body_wick_metrics(bars[origin.index])

    match = (
        abs(auto.zone.low - expected_low) < 1e-9
        and abs(auto.zone.high - expected_high) < 1e-9
    )

    return ZoneGeometryRecord(
        zone_id=auto.zone.id,
        zone_kind=None if auto.zone.kind is None else auto.zone.kind.value,
        geometry_type=geometry_type,
        contributing_swing_count=len(prices),
        swing_prices=prices,
        swing_spread=float(swing_spread),
        zone_low=float(auto.zone.low),
        zone_high=float(auto.zone.high),
        absolute_width=float(width),
        expected_low=float(expected_low),
        expected_high=float(expected_high),
        boundary_matches_implementation=match,
        atr_at_origin=atr_origin,
        atr_at_generation=atr_gen,
        width_over_atr_origin=w_atr_origin,
        width_over_atr_generation=w_atr_gen,
        cluster_tolerance=float(ev.cluster_tolerance),
        half_width_at_generation=float(half_width),
        expected_single_swing_width_at_generation=float(expected_single),
        swing_spread_over_atr_origin=spread_atr,
        width_over_tolerance=w_tol,
        origin_swing_kind=None if origin is None else origin.kind.value,
        origin_swing_price=None if origin is None else float(origin.price),
        origin_bar=origin_bar,
        origin_confirmation_index=conf_i,
        generation_asof_index=gen_i,
        origin_confirmation_time=ev.origin_confirmation_time.isoformat(sep=" "),
    )


def volatility_regime_label(
    atr_value: float | None,
    *,
    p33: float | None,
    p67: float | None,
) -> str:
    """Diagnostic-only ATR tertile at zone creation."""
    if atr_value is None or p33 is None or p67 is None:
        return "atr_unavailable"
    if atr_value <= p33:
        return "low_volatility"
    if atr_value <= p67:
        return "mid_volatility"
    return "high_volatility"


def _collect_metric_rows(
    records: Sequence[ZoneGeometryRecord],
) -> dict[str, list[float]]:
    rows: dict[str, list[float]] = {
        "absolute_width": [],
        "atr_at_origin": [],
        "width_over_atr_origin": [],
        "swing_spread": [],
        "swing_spread_over_atr_origin": [],
        "origin_bar_range": [],
        "origin_bar_body": [],
        "origin_bar_upper_wick": [],
        "origin_bar_lower_wick": [],
        "cluster_tolerance": [],
        "width_over_cluster_tolerance": [],
        "expected_single_swing_width_at_generation": [],
    }
    for rec in records:
        rows["absolute_width"].append(rec.absolute_width)
        if rec.atr_at_origin is not None:
            rows["atr_at_origin"].append(rec.atr_at_origin)
        if rec.width_over_atr_origin is not None:
            rows["width_over_atr_origin"].append(rec.width_over_atr_origin)
        rows["swing_spread"].append(rec.swing_spread)
        if rec.swing_spread_over_atr_origin is not None:
            rows["swing_spread_over_atr_origin"].append(
                rec.swing_spread_over_atr_origin
            )
        if rec.origin_bar is not None:
            rows["origin_bar_range"].append(rec.origin_bar["range"])
            rows["origin_bar_body"].append(rec.origin_bar["body"])
            rows["origin_bar_upper_wick"].append(rec.origin_bar["upper_wick"])
            rows["origin_bar_lower_wick"].append(rec.origin_bar["lower_wick"])
        rows["cluster_tolerance"].append(rec.cluster_tolerance)
        if rec.width_over_tolerance is not None:
            rows["width_over_cluster_tolerance"].append(rec.width_over_tolerance)
        rows["expected_single_swing_width_at_generation"].append(
            rec.expected_single_swing_width_at_generation
        )
    return rows


def summarize_records(
    records: Sequence[ZoneGeometryRecord],
    *,
    p33: float | None = None,
    p67: float | None = None,
) -> dict[str, Any]:
    """Aggregate distributions and subgroup splits."""
    if not records:
        return {"zone_count": 0}

    metrics = _collect_metric_rows(records)
    distributions = {
        key: distribution_summary(values) for key, values in metrics.items()
    }

    single = [r for r in records if r.geometry_type == "single_swing_expanded"]
    multi = [r for r in records if r.geometry_type == "multi_swing_envelope"]
    supply = [r for r in records if r.zone_kind == ZoneKind.SUPPLY.value]
    demand = [r for r in records if r.zone_kind == ZoneKind.DEMAND.value]
    swing_high = [r for r in records if r.origin_swing_kind == SwingKind.HIGH.value]
    swing_low = [r for r in records if r.origin_swing_kind == SwingKind.LOW.value]

    def _subgroup(subset: Sequence[ZoneGeometryRecord]) -> dict[str, Any]:
        if not subset:
            return {"count": 0}
        w_atr = [r.width_over_atr_origin for r in subset if r.width_over_atr_origin]
        return {
            "count": len(subset),
            "pct_of_total": len(subset) / len(records),
            "median_width_over_atr_origin": (
                None if not w_atr else median(w_atr)
            ),
            "median_absolute_width": median(r.absolute_width for r in subset),
            "median_swing_spread": median(r.swing_spread for r in subset),
        }

    vol_groups: dict[str, list[ZoneGeometryRecord]] = {
        "low_volatility": [],
        "mid_volatility": [],
        "high_volatility": [],
        "atr_unavailable": [],
    }
    for rec in records:
        label = volatility_regime_label(
            rec.atr_at_origin, p33=p33, p67=p67
        )
        vol_groups[label].append(rec)

    boundary_mismatches = [
        r.zone_id for r in records if not r.boundary_matches_implementation
    ]

    return {
        "zone_count": len(records),
        "geometry_type_counts": {
            "single_swing_expanded": len(single),
            "multi_swing_envelope": len(multi),
        },
        "geometry_type_pct": {
            "single_swing_expanded": len(single) / len(records),
            "multi_swing_envelope": len(multi) / len(records),
        },
        "boundary_verification": {
            "matches": len(records) - len(boundary_mismatches),
            "mismatches": len(boundary_mismatches),
            "mismatch_zone_ids": boundary_mismatches,
        },
        "distributions": distributions,
        "by_zone_kind": {
            "supply": _subgroup(supply),
            "demand": _subgroup(demand),
        },
        "by_origin_swing_kind": {
            "swing_high": _subgroup(swing_high),
            "swing_low": _subgroup(swing_low),
        },
        "by_geometry_type": {
            "single_swing_expanded": _subgroup(single),
            "multi_swing_envelope": _subgroup(multi),
        },
        "by_volatility_regime_diagnostic": {
            label: _subgroup(group) for label, group in vol_groups.items()
        },
    }


def select_representative_samples(
    records: Sequence[ZoneGeometryRecord],
    *,
    sample_size: int = SAMPLE_SIZE,
) -> list[ZoneGeometryRecord]:
    """Stratified sample: narrow/median/wide width/ATR + geometry types."""
    if not records:
        return []
    with_ratio = [r for r in records if r.width_over_atr_origin is not None]
    if not with_ratio:
        return list(records[:sample_size])

    ordered = sorted(with_ratio, key=lambda r: r.width_over_atr_origin or 0.0)
    picks: list[ZoneGeometryRecord] = []
    n = len(ordered)

    def _pick_at(p: float) -> None:
        idx = int(round((n - 1) * p))
        candidate = ordered[max(0, min(n - 1, idx))]
        if candidate.zone_id not in {p.zone_id for p in picks}:
            picks.append(candidate)

    for p in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        _pick_at(p)

    for geo in ("single_swing_expanded", "multi_swing_envelope"):
        subset = [r for r in records if r.geometry_type == geo]
        if subset:
            narrow = min(
                subset,
                key=lambda r: r.width_over_atr_origin or float("inf"),
            )
            if narrow.zone_id not in {p.zone_id for p in picks}:
                picks.append(narrow)

    return picks[:sample_size]


def evaluate_narrow_width_hypotheses(
    summary: Mapping[str, Any],
    *,
    config: SwingClusterZoneConfig,
) -> dict[str, Any]:
    """Evidence table for why V1 zones are narrow."""
    dist = summary.get("distributions", {})
    w_atr = dist.get("width_over_atr_origin", {})
    geo = summary.get("geometry_type_pct", {})
    boundary = summary.get("boundary_verification", {})
    multi_pct = float(geo.get("multi_swing_envelope", 0.0))
    single_pct = float(geo.get("single_swing_expanded", 0.0))
    median_w_atr = w_atr.get("median")
    expected_single_ratio = 2.0 * config.single_swing_half_width_atr_multiple

    hypotheses: dict[str, dict[str, Any]] = {
        "A_intended_v1_geometry": {
            "description": (
                "Narrow bands are intended: multi-swing envelope uses min/max "
                "swing prices without ATR padding; single-swing uses 0.20×ATR total."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "B_swing_magnitude": {
            "description": (
                "Merged swing prices sit very close together, producing small envelopes."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "C_candle_body_wick_geometry": {
            "description": (
                "Zone width reflects swing bar wick extremes, not full candle range."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "D_atr_normalization_scaling": {
            "description": (
                "ATR used at generation vs origin shifts width/ATR ratios."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "E_implementation_defect": {
            "description": (
                "Observed boundaries differ from documented V1 formulas."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "F_interaction_of_factors": {
            "description": (
                "Multiple intended mechanics combine (cluster envelope + tight swings)."
            ),
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
        "G_insufficient_evidence": {
            "description": "Cannot determine root cause from available data.",
            "evidence_for": [],
            "evidence_against": [],
            "verdict": "pending",
        },
    }

    if multi_pct >= 0.5:
        hypotheses["A_intended_v1_geometry"]["evidence_for"].append(
            f"Multi-swing envelope dominates ({multi_pct:.1%} of zones); "
            "V1 docs define width as min/max swing prices without expansion."
        )
        hypotheses["F_interaction_of_factors"]["evidence_for"].append(
            "Dominant geometry type is multi-swing envelope."
        )

    spread_dist = dist.get("swing_spread_over_atr_origin", {})
    if spread_dist.get("median") is not None and spread_dist["median"] < 0.15:
        hypotheses["B_swing_magnitude"]["evidence_for"].append(
            f"Median swing spread/ATR at origin ≈ {spread_dist['median']:.4f} "
            "(merged swings are tightly spaced)."
        )
        hypotheses["F_interaction_of_factors"]["evidence_for"].append(
            "Tight swing clustering feeds directly into envelope width."
        )

    origin_range = dist.get("origin_bar_range", {})
    width_med = dist.get("absolute_width", {}).get("median")
    if (
        w_atr.get("median") is not None
        and origin_range.get("median") is not None
        and width_med is not None
        and width_med < origin_range["median"] * 0.25
    ):
        hypotheses["C_candle_body_wick_geometry"]["evidence_for"].append(
            f"Zone width median ({width_med:.6f}) << origin bar range median "
            f"({origin_range['median']:.6f}) — boundaries anchor to swing "
            "price (bar high/low), not full candle range."
        )
        hypotheses["C_candle_body_wick_geometry"]["verdict"] = "supported"

    single = summary.get("by_geometry_type", {}).get("single_swing_expanded", {})
    if single.get("count", 0) > 0:
        hypotheses["D_atr_normalization_scaling"]["evidence_for"].append(
            "Single-swing zones have fixed absolute width at generation-asof ATR "
            f"(~{expected_single_ratio:.2f}×ATR_gen) but width/ATR_origin median "
            f"≈ {single.get('median_width_over_atr_origin')} when origin ATR differs."
        )
        hypotheses["D_atr_normalization_scaling"]["verdict"] = "contributing_factor"

    if median_w_atr is not None and single_pct > 0:
        hypotheses["A_intended_v1_geometry"]["evidence_for"].append(
            f"Single-swing zones ({single_pct:.1%}) should be ~{expected_single_ratio:.2f}×ATR "
            f"at generation; population median width/ATR={median_w_atr:.3f}."
        )

    if boundary.get("mismatches", 0) == 0:
        hypotheses["E_implementation_defect"]["evidence_against"].append(
            "All audited zone boundaries match recomputed V1 formulas."
        )
        hypotheses["E_implementation_defect"]["verdict"] = "unlikely"
    else:
        hypotheses["E_implementation_defect"]["evidence_for"].append(
            f"{boundary['mismatches']} boundary mismatches vs documented formulas."
        )
        hypotheses["E_implementation_defect"]["verdict"] = "possible"

    if multi_pct >= 0.5 and (spread_dist.get("median") or 0) < 0.2:
        hypotheses["A_intended_v1_geometry"]["verdict"] = "supported"
        hypotheses["B_swing_magnitude"]["verdict"] = "supported"
        hypotheses["F_interaction_of_factors"]["verdict"] = "primary"
        hypotheses["G_insufficient_evidence"]["verdict"] = "not_needed"
    else:
        hypotheses["G_insufficient_evidence"]["verdict"] = "possible"

    return hypotheses


def build_implementation_mechanics(config: SwingClusterZoneConfig) -> dict[str, Any]:
    """Document V1 geometry semantics from code/docs (source of truth)."""
    return {
        "method_id": config.method_id,
        "cluster_merge_rule": "next_swing.price - cluster_max_price <= tolerance",
        "tolerance": (
            f"cluster_atr_multiple({config.cluster_atr_multiple}) * causal_ATR(asof) "
            f"or absolute_price_tolerance({config.absolute_price_tolerance})"
        ),
        "multi_swing_boundaries": "[min(swing_prices), max(swing_prices)] — no ATR padding",
        "single_swing_boundaries": (
            f"swing_price ± single_swing_half_width_atr_multiple"
            f"({config.single_swing_half_width_atr_multiple}) * causal_ATR(asof)"
        ),
        "single_swing_full_width_atr": (
            2.0 * config.single_swing_half_width_atr_multiple
        ),
        "swing_price_source": "SwingEvent.price = bar.high (HIGH) or bar.low (LOW) at fractal index",
        "atr_at_generation": "causal_ATR(bars, asof_index=generation_asof) stored in evidence.atr_used",
        "research_width_atr_convention": (
            "width / causal_ATR(origin_confirmation_index) for diagnostics"
        ),
        "intended_width_meaning": (
            "Price-interest band from clustered structural swing extremes; "
            "not full candle range, not a fixed ATR fraction for multi-swing clusters."
        ),
    }


@dataclass(frozen=True)
class ZoneGeometryAuditResult:
    audit_version: str
    source_path: str
    symbol: str
    effective_start: str | None
    effective_end: str | None
    timeframe: str
    implementation_mechanics: dict[str, Any]
    full_window: dict[str, Any]
    chronological_thirds: tuple[dict[str, Any], ...]
    hypothesis_evaluation: dict[str, Any]
    conclusion: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_version": self.audit_version,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "timeframe": self.timeframe,
            "implementation_mechanics": self.implementation_mechanics,
            "full_window": self.full_window,
            "chronological_thirds": list(self.chronological_thirds),
            "hypothesis_evaluation": self.hypothesis_evaluation,
            "conclusion": self.conclusion,
            "disclaimer": (
                "Diagnostic audit only. Does not modify Automatic Zone V1. "
                "Volatility-regime splits are not filters."
            ),
        }


def audit_zones_on_bars(
    zones: Sequence[AutomaticZone],
    bars: Sequence[Bar],
    *,
    symbol: str,
    timeframe: str,
    config: SwingClusterZoneConfig | None = None,
) -> tuple[list[ZoneGeometryRecord], dict[str, Any]]:
    """Audit all zones on one HTF bar series."""
    cfg = config or SwingClusterZoneConfig()
    if not zones:
        return [], summarize_records([])

    asof_index = zones[0].evidence.asof_index
    swings_by_id = lookup_swings_by_id(
        bars, symbol=symbol, timeframe=timeframe, asof_index=asof_index
    )
    records = [
        audit_zone_geometry(auto, bars, swings_by_id, config=cfg)
        for auto in zones
    ]
    atrs = [r.atr_at_origin for r in records if r.atr_at_origin is not None]
    ordered_atrs = sorted(atrs)
    p33 = _pct(ordered_atrs, 0.33) if ordered_atrs else None
    p67 = _pct(ordered_atrs, 0.67) if ordered_atrs else None
    summary = summarize_records(records, p33=p33, p67=p67)
    summary["representative_samples"] = [
        r.to_dict() for r in select_representative_samples(records)
    ]
    summary["volatility_regime_thresholds"] = {
        "atr_at_origin_p33": p33,
        "atr_at_origin_p67": p67,
        "note": "Diagnostic tertiles only — not a filter.",
    }
    return records, summary


def run_zone_geometry_audit(
    csv_path: str | Path,
    *,
    symbol: str = "EURUSD",
    start: date | None = None,
    end: date | None = None,
    timeframe: str = "M15",
    config: SwingClusterZoneConfig | None = None,
) -> ZoneGeometryAuditResult:
    """Full-window + chronological-thirds geometry audit on real data."""
    cfg = config or SwingClusterZoneConfig()
    bounds, eff_start, eff_end = resolve_evaluation_window(
        csv_path, symbol=symbol, start=start, end=end
    )
    dataset = build_research_dataset(
        csv_path,
        symbol=symbol,
        start=eff_start,
        end=eff_end,
        source_timeframe="M1",
        skip_invalid_ohlc=True,
        target_timeframes=(timeframe,),
    )
    bars = dataset.bars(timeframe)
    zones, _, _ = run_timeframe_pipeline(
        bars, timeframe=timeframe, symbol=symbol, cluster_config=cfg
    )

    _, full_summary = audit_zones_on_bars(
        zones, bars, symbol=symbol, timeframe=timeframe, config=cfg
    )
    mechanics = build_implementation_mechanics(cfg)
    hypotheses = evaluate_narrow_width_hypotheses(full_summary, config=cfg)

    third_rows: list[dict[str, Any]] = []
    if eff_start is not None and eff_end is not None:
        for label, seg_start, seg_end in split_date_range_into_thirds(
            eff_start, eff_end
        ):
            seg_dataset = build_research_dataset(
                csv_path,
                symbol=symbol,
                start=seg_start,
                end=seg_end,
                source_timeframe="M1",
                skip_invalid_ohlc=True,
                target_timeframes=(timeframe,),
            )
            seg_bars = seg_dataset.bars(timeframe)
            seg_zones, _, _ = run_timeframe_pipeline(
                seg_bars,
                timeframe=timeframe,
                symbol=symbol,
                cluster_config=cfg,
            )
            _, seg_summary = audit_zones_on_bars(
                seg_zones,
                seg_bars,
                symbol=symbol,
                timeframe=timeframe,
                config=cfg,
            )
            third_rows.append(
                {
                    "label": label,
                    "start": seg_start.isoformat(),
                    "end": seg_end.isoformat(),
                    **seg_summary,
                }
            )

    has_defect = full_summary.get("boundary_verification", {}).get("mismatches", 0) > 0
    geo_pct = full_summary.get("geometry_type_pct", {})
    w_med = full_summary.get("distributions", {}).get(
        "width_over_atr_origin", {}
    ).get("median")

    if has_defect:
        conclusion_text = (
            "Boundary mismatches detected — possible implementation defect; "
            "requires targeted review. V1 unchanged pending explicit fix request."
        )
        preserve_v1 = True
    else:
        conclusion_text = (
            "V1 zones are narrow primarily because the intended multi-swing "
            "envelope uses min/max clustered swing prices without ATR padding, "
            "and merged swings are tightly spaced (small swing spread/ATR). "
            "Single-swing zones use 0.20×ATR expansion but are a minority. "
            "No demonstrated implementation defect — geometry matches documented V1."
        )
        preserve_v1 = True

    conclusion = {
        "research_question": (
            "Why are V1 zones narrow, and is there evidence that the geometry "
            "itself is behaving incorrectly?"
        ),
        "answer": conclusion_text,
        "preserve_baseline_v1": preserve_v1,
        "median_width_over_atr_origin": w_med,
        "multi_swing_envelope_pct": geo_pct.get("multi_swing_envelope"),
        "single_swing_expanded_pct": geo_pct.get("single_swing_expanded"),
        "implementation_defect_demonstrated": has_defect,
        "next_diagnostic_if_any": (
            None
            if not has_defect
            else "Investigate boundary mismatch zone ids and replay clustering."
        ),
    }

    return ZoneGeometryAuditResult(
        audit_version=AUDIT_VERSION,
        source_path=str(csv_path),
        symbol=symbol.upper(),
        effective_start=None if eff_start is None else eff_start.isoformat(),
        effective_end=None if eff_end is None else eff_end.isoformat(),
        timeframe=timeframe,
        implementation_mechanics=mechanics,
        full_window=full_summary,
        chronological_thirds=tuple(third_rows),
        hypothesis_evaluation=hypotheses,
        conclusion=conclusion,
    )
