"""LiquidityView — requires method_id; no pack in Phase 1 defaults."""

from __future__ import annotations

from dataclasses import dataclass

from core.features.context import FeatureContext
from core.features.types import MethodId
from core.features.views.base import UnsupportedMethodError, require_method_id


@dataclass(frozen=True)
class LiquidityProjection:
    method_id: str
    reason: str


class LiquidityView:
    """Pure liquidity projections. No default dialect pack in Phase 1."""

    def project(
        self, context: FeatureContext, method_id: MethodId | str
    ) -> LiquidityProjection:
        _ = context
        method = require_method_id(method_id)
        raise UnsupportedMethodError(
            f"Liquidity method {method!r} has no materialized liquidity pack in Phase 1"
        )
