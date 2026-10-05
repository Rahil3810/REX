"""MomentumView — return-based momentum projections (not range expansion)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.features.context import FeatureContext
from core.features.packs.base import PricePack
from core.features.types import METHOD_MOMENTUM_TS_MOM_V1, PACK_PRICE, MethodId
from core.features.views.base import UnsupportedMethodError, require_method_id


class MomentumDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MomentumProjection:
    method_id: str
    direction: MomentumDirection
    strength: float
    reason: str


class MomentumView:
    """Pure momentum projections over PricePack returns."""

    def project(
        self, context: FeatureContext, method_id: MethodId | str
    ) -> MomentumProjection:
        method = require_method_id(method_id)
        if method != METHOD_MOMENTUM_TS_MOM_V1:
            raise UnsupportedMethodError(
                f"Unknown momentum method_id: {method!r}. "
                "Range expansion belongs to VolatilityView.range_expansion_v1."
            )

        pack = context.require_pack(PACK_PRICE, PricePack)
        assert isinstance(pack, PricePack)
        entry = pack.returns.by_timeframe.get(context.entry_timeframe)
        if entry is None or not entry.simple_returns:
            return MomentumProjection(
                method_id=method,
                direction=MomentumDirection.UNKNOWN,
                strength=0.0,
                reason="No returns available for time-series momentum.",
            )

        lookback = min(20, len(entry.simple_returns))
        window = entry.simple_returns[-lookback:]
        cumulative = sum(window)
        strength = abs(cumulative)
        if cumulative > 0:
            direction = MomentumDirection.BULLISH
        elif cumulative < 0:
            direction = MomentumDirection.BEARISH
        else:
            direction = MomentumDirection.NEUTRAL
        return MomentumProjection(
            method_id=method,
            direction=direction,
            strength=strength,
            reason=(
                f"ts_mom_v1 cumulative simple return over {lookback} bars: "
                f"{cumulative:.6f}."
            ),
        )
