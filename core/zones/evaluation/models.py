"""Zone Evaluation V1 result models — raw measurements, not confidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from statistics import median
from typing import Any

from core.zones.evaluation.config import ZoneEvaluationConfig
from models.zone import ZoneKind


class InteractionOutcome(StrEnum):
    """Outcome of one zone interaction under ``zone_eval_v1``."""

    SUCCESS = "success"
    FAILURE = "failure"
    BROKEN = "broken"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ZoneInteractionEvaluation:
    """Per-interaction evidence for a zone under a fixed methodology."""

    zone_id: int
    interaction_index: int
    entry_index: int
    entry_time: datetime
    exit_index: int | None
    exit_time: datetime | None
    atr_at_interaction: float | None
    mfe: float | None
    mae: float | None
    bars_to_target: int | None
    bars_to_adverse: int | None
    outcome: InteractionOutcome
    break_detected: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "interaction_index": self.interaction_index,
            "entry_index": self.entry_index,
            "entry_time": self.entry_time.isoformat(),
            "exit_index": self.exit_index,
            "exit_time": None if self.exit_time is None else self.exit_time.isoformat(),
            "atr_at_interaction": self.atr_at_interaction,
            "mfe": self.mfe,
            "mae": self.mae,
            "bars_to_target": self.bars_to_target,
            "bars_to_adverse": self.bars_to_adverse,
            "outcome": self.outcome.value,
            "break_detected": self.break_detected,
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> ZoneInteractionEvaluation:
        return ZoneInteractionEvaluation(
            zone_id=int(payload["zone_id"]),  # type: ignore[arg-type]
            interaction_index=int(payload["interaction_index"]),  # type: ignore[arg-type]
            entry_index=int(payload["entry_index"]),  # type: ignore[arg-type]
            entry_time=datetime.fromisoformat(str(payload["entry_time"])),
            exit_index=(
                None
                if payload.get("exit_index") is None
                else int(payload["exit_index"])  # type: ignore[arg-type]
            ),
            exit_time=(
                None
                if payload.get("exit_time") is None
                else datetime.fromisoformat(str(payload["exit_time"]))
            ),
            atr_at_interaction=(
                None
                if payload.get("atr_at_interaction") is None
                else float(payload["atr_at_interaction"])  # type: ignore[arg-type]
            ),
            mfe=(
                None
                if payload.get("mfe") is None
                else float(payload["mfe"])  # type: ignore[arg-type]
            ),
            mae=(
                None
                if payload.get("mae") is None
                else float(payload["mae"])  # type: ignore[arg-type]
            ),
            bars_to_target=(
                None
                if payload.get("bars_to_target") is None
                else int(payload["bars_to_target"])  # type: ignore[arg-type]
            ),
            bars_to_adverse=(
                None
                if payload.get("bars_to_adverse") is None
                else int(payload["bars_to_adverse"])  # type: ignore[arg-type]
            ),
            outcome=InteractionOutcome(str(payload["outcome"])),
            break_detected=bool(payload["break_detected"]),
            reason=str(payload.get("reason", "")),
        )


@dataclass(frozen=True)
class ZoneEvaluation:
    """Aggregate historical measurements for one zone under ``zone_eval_v1``.

    Does not redefine ``Zone.strength``. Does not represent confidence.
    """

    zone_id: int
    symbol: str
    timeframe: str
    zone_kind: ZoneKind | None
    evaluated_at: datetime
    sample_count: int
    touch_count: int
    """Independent interaction episodes (alias of sample_count for clarity)."""

    successful_reaction_count: int
    failed_reaction_count: int
    broken_count: int
    unavailable_count: int
    success_rate: float | None
    """successful / (success+failure+broken); None if no evaluable interactions."""

    average_max_favorable_excursion: float | None
    average_max_adverse_excursion: float | None
    median_mfe: float | None
    median_mae: float | None
    average_bars_to_reaction: float | None
    evaluation_horizon: int
    atr_multiple_target: float
    atr_multiple_stop: float
    method_id: str
    config: ZoneEvaluationConfig
    interactions: tuple[ZoneInteractionEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "zone_kind": None if self.zone_kind is None else self.zone_kind.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "sample_count": self.sample_count,
            "touch_count": self.touch_count,
            "successful_reaction_count": self.successful_reaction_count,
            "failed_reaction_count": self.failed_reaction_count,
            "broken_count": self.broken_count,
            "unavailable_count": self.unavailable_count,
            "success_rate": self.success_rate,
            "average_max_favorable_excursion": self.average_max_favorable_excursion,
            "average_max_adverse_excursion": self.average_max_adverse_excursion,
            "median_MFE": self.median_mfe,
            "median_MAE": self.median_mae,
            "average_bars_to_reaction": self.average_bars_to_reaction,
            "evaluation_horizon": self.evaluation_horizon,
            "atr_multiple_target": self.atr_multiple_target,
            "atr_multiple_stop": self.atr_multiple_stop,
            "method_id": self.method_id,
            "config": self.config.to_dict(),
            "interactions": [item.to_dict() for item in self.interactions],
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> ZoneEvaluation:
        kind_raw = payload.get("zone_kind")
        kind = None if kind_raw is None else ZoneKind(str(kind_raw))
        interactions = tuple(
            ZoneInteractionEvaluation.from_dict(item)
            for item in payload.get("interactions", [])  # type: ignore[union-attr]
        )
        config = ZoneEvaluationConfig.from_dict(payload.get("config", {}))  # type: ignore[arg-type]
        return ZoneEvaluation(
            zone_id=int(payload["zone_id"]),  # type: ignore[arg-type]
            symbol=str(payload["symbol"]),
            timeframe=str(payload["timeframe"]),
            zone_kind=kind,
            evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
            sample_count=int(payload["sample_count"]),  # type: ignore[arg-type]
            touch_count=int(payload["touch_count"]),  # type: ignore[arg-type]
            successful_reaction_count=int(payload["successful_reaction_count"]),  # type: ignore[arg-type]
            failed_reaction_count=int(payload["failed_reaction_count"]),  # type: ignore[arg-type]
            broken_count=int(payload["broken_count"]),  # type: ignore[arg-type]
            unavailable_count=int(payload.get("unavailable_count", 0)),  # type: ignore[arg-type]
            success_rate=(
                None
                if payload.get("success_rate") is None
                else float(payload["success_rate"])  # type: ignore[arg-type]
            ),
            average_max_favorable_excursion=(
                None
                if payload.get("average_max_favorable_excursion") is None
                else float(payload["average_max_favorable_excursion"])  # type: ignore[arg-type]
            ),
            average_max_adverse_excursion=(
                None
                if payload.get("average_max_adverse_excursion") is None
                else float(payload["average_max_adverse_excursion"])  # type: ignore[arg-type]
            ),
            median_mfe=(
                None
                if payload.get("median_MFE", payload.get("median_mfe")) is None
                else float(payload.get("median_MFE", payload.get("median_mfe")))  # type: ignore[arg-type]
            ),
            median_mae=(
                None
                if payload.get("median_MAE", payload.get("median_mae")) is None
                else float(payload.get("median_MAE", payload.get("median_mae")))  # type: ignore[arg-type]
            ),
            average_bars_to_reaction=(
                None
                if payload.get("average_bars_to_reaction") is None
                else float(payload["average_bars_to_reaction"])  # type: ignore[arg-type]
            ),
            evaluation_horizon=int(payload["evaluation_horizon"]),  # type: ignore[arg-type]
            atr_multiple_target=float(payload["atr_multiple_target"]),  # type: ignore[arg-type]
            atr_multiple_stop=float(payload["atr_multiple_stop"]),  # type: ignore[arg-type]
            method_id=str(payload["method_id"]),
            config=config,
            interactions=interactions,
        )


def aggregate_interactions(
    *,
    zone_id: int,
    symbol: str,
    timeframe: str,
    zone_kind: ZoneKind | None,
    evaluated_at: datetime,
    config: ZoneEvaluationConfig,
    interactions: Sequence[ZoneInteractionEvaluation],
) -> ZoneEvaluation:
    """Build aggregate ZoneEvaluation from per-interaction evidence."""
    items = tuple(interactions)
    success = sum(1 for i in items if i.outcome is InteractionOutcome.SUCCESS)
    failure = sum(1 for i in items if i.outcome is InteractionOutcome.FAILURE)
    broken = sum(1 for i in items if i.outcome is InteractionOutcome.BROKEN)
    unavailable = sum(1 for i in items if i.outcome is InteractionOutcome.UNAVAILABLE)
    evaluable = success + failure + broken
    success_rate = (success / evaluable) if evaluable > 0 else None

    mfe_values = [i.mfe for i in items if i.mfe is not None]
    mae_values = [i.mae for i in items if i.mae is not None]
    bars_to = [i.bars_to_target for i in items if i.bars_to_target is not None]

    return ZoneEvaluation(
        zone_id=zone_id,
        symbol=symbol,
        timeframe=timeframe,
        zone_kind=zone_kind,
        evaluated_at=evaluated_at,
        sample_count=len(items),
        touch_count=len(items),
        successful_reaction_count=success,
        failed_reaction_count=failure,
        broken_count=broken,
        unavailable_count=unavailable,
        success_rate=success_rate,
        average_max_favorable_excursion=(
            sum(mfe_values) / len(mfe_values) if mfe_values else None
        ),
        average_max_adverse_excursion=(
            sum(mae_values) / len(mae_values) if mae_values else None
        ),
        median_mfe=float(median(mfe_values)) if mfe_values else None,
        median_mae=float(median(mae_values)) if mae_values else None,
        average_bars_to_reaction=(
            sum(bars_to) / len(bars_to) if bars_to else None
        ),
        evaluation_horizon=config.horizon_bars,
        atr_multiple_target=config.target_atr_multiple,
        atr_multiple_stop=config.invalidation_atr_multiple,
        method_id=config.method_id,
        config=config,
        interactions=items,
    )
