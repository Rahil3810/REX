"""Zone Evaluation V1 configuration (serializable methodology)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


METHOD_ZONE_EVAL_V1 = "zone_eval_v1"


@dataclass(frozen=True)
class ZoneEvaluationConfig:
    """Serializable parameters for ``zone_eval_v1``.

    Measurements are ATR-normalized. This is a research methodology definition,
    not a claim of zone "accuracy" or confidence.
    """

    method_id: str = METHOD_ZONE_EVAL_V1
    atr_period: int = 14
    target_atr_multiple: float = 1.0
    """Favorable move required for SUCCESS (× ATR at interaction)."""

    invalidation_atr_multiple: float = 0.5
    """Adverse move that counts as FAILURE before target (× ATR)."""

    horizon_bars: int = 20
    """Maximum bars after interaction entry used for MFE/MAE / outcomes."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "atr_period": self.atr_period,
            "target_atr": self.target_atr_multiple,
            "invalidation_atr": self.invalidation_atr_multiple,
            "horizon_bars": self.horizon_bars,
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> ZoneEvaluationConfig:
        return ZoneEvaluationConfig(
            method_id=str(payload.get("method_id", METHOD_ZONE_EVAL_V1)),
            atr_period=int(payload.get("atr_period", 14)),  # type: ignore[arg-type]
            target_atr_multiple=float(
                payload.get("target_atr", payload.get("target_atr_multiple", 1.0))
            ),
            invalidation_atr_multiple=float(
                payload.get(
                    "invalidation_atr",
                    payload.get("invalidation_atr_multiple", 0.5),
                )
            ),
            horizon_bars=int(payload.get("horizon_bars", 20)),  # type: ignore[arg-type]
        )
