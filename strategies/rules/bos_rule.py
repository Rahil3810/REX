"""Structural BOS entrypoint for strategy-layer imports.

This module no longer implements lookback breakout. Use
``LookbackBreakoutRule`` from ``strategies.rules.lookback_breakout_rule``
for the old max/min-window behavior.

Canonical structural BOS is ``detect_swing_bos`` / ``detect_swing_bos_series``
in ``core.features.generators.bos`` (method_id ``swing_bos_v1``).
"""

from core.features.generators.bos import (
    BOSDirection,
    StructuralBOSEvent,
    StructuralBOSResult,
    detect_swing_bos,
    detect_swing_bos_series,
)

__all__ = [
    "BOSDirection",
    "StructuralBOSEvent",
    "StructuralBOSResult",
    "detect_swing_bos",
    "detect_swing_bos_series",
]
