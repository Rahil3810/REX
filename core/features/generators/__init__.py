"""Feature generators package."""

from core.features.generators.protocols import DerivedGenerator, PrimitiveGenerator
from core.features.generators.range_expansion import (
    RangeExpansionFeatures,
    RangeExpansionGenerator,
)
from core.features.generators.returns import ReturnFeatures, ReturnsGenerator
from core.features.generators.bos import (
    BOSDirection,
    StructuralBOSEvent,
    StructuralBOSResult,
    detect_swing_bos,
    detect_swing_bos_series,
)
from core.features.generators.protocols import DerivedGenerator, PrimitiveGenerator
from core.features.generators.range_expansion import (
    RangeExpansionFeatures,
    RangeExpansionGenerator,
)
from core.features.generators.returns import ReturnFeatures, ReturnsGenerator
from core.features.generators.swings import (
    SwingEvent,
    SwingFeatures,
    SwingGenerator,
    SwingKind,
    TimeframeSwings,
    make_swing_id,
)

__all__ = [
    "BOSDirection",
    "DerivedGenerator",
    "PrimitiveGenerator",
    "RangeExpansionFeatures",
    "RangeExpansionGenerator",
    "ReturnFeatures",
    "ReturnsGenerator",
    "StructuralBOSEvent",
    "StructuralBOSResult",
    "SwingEvent",
    "SwingFeatures",
    "SwingGenerator",
    "SwingKind",
    "TimeframeSwings",
    "detect_swing_bos",
    "detect_swing_bos_series",
    "make_swing_id",
]
