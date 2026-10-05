"""VolatilityView — range expansion and related projections."""

from __future__ import annotations

from dataclasses import dataclass

from core.features.context import FeatureContext
from core.features.packs.base import VolatilityPack
from core.features.types import (
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PACK_VOLATILITY,
    MethodId,
)
from core.features.views.base import UnsupportedMethodError, require_method_id
from models.market_structure import RangeExpansionState


@dataclass(frozen=True)
class RangeExpansionProjection:
    method_id: str
    state: RangeExpansionState
    reason: str
    ratio: float | None


class VolatilityView:
    """Pure volatility projections. Range expansion is not momentum."""

    def project(
        self, context: FeatureContext, method_id: MethodId | str
    ) -> RangeExpansionProjection:
        method = require_method_id(method_id)
        if method != METHOD_VOLATILITY_RANGE_EXPANSION_V1:
            raise UnsupportedMethodError(f"Unknown volatility method_id: {method!r}")
        pack = context.require_pack(PACK_VOLATILITY, VolatilityPack)
        assert isinstance(pack, VolatilityPack)
        return RangeExpansionProjection(
            method_id=method,
            state=pack.range_expansion.state,
            reason=pack.range_expansion.reason,
            ratio=pack.range_expansion.ratio,
        )
