"""In-memory FeatureRepository architecture for REX research."""

from core.features.config import (
    FeatureConfig,
    default_feature_config,
    load_feature_config,
)
from core.features.context import FeatureContext
from core.features.repository import FeatureRepository
from core.features.timeframes import (
    aggregate_completed_bars,
    ensure_utc,
    prepare_causal_bars,
)
from core.features.generators.bos import (
    BOSDirection,
    StructuralBOSEvent,
    StructuralBOSResult,
    detect_swing_bos,
    detect_swing_bos_series,
)
from core.features.types import (
    DEFAULT_PACK_IDS,
    METHOD_MOMENTUM_TS_MOM_V1,
    METHOD_PHASE_HEURISTIC_V1,
    METHOD_STRUCTURE_SWING_BOS_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
    PACK_ZONES,
    PackId,
)
from core.features.views import (
    LiquidityView,
    MomentumView,
    PhaseView,
    TrendView,
    UnsupportedMethodError,
    VolatilityView,
)

__all__ = [
    "BOSDirection",
    "DEFAULT_PACK_IDS",
    "FeatureConfig",
    "FeatureContext",
    "FeatureRepository",
    "LiquidityView",
    "METHOD_MOMENTUM_TS_MOM_V1",
    "METHOD_PHASE_HEURISTIC_V1",
    "METHOD_STRUCTURE_SWING_BOS_V1",
    "METHOD_TREND_MARKET_STRUCTURE_V1",
    "METHOD_VOLATILITY_RANGE_EXPANSION_V1",
    "MomentumView",
    "PACK_INDICATORS",
    "PACK_PRICE",
    "PACK_SESSION",
    "PACK_STRUCTURE",
    "PACK_VOLATILITY",
    "PACK_ZONES",
    "PackId",
    "PhaseView",
    "StructuralBOSEvent",
    "StructuralBOSResult",
    "TrendView",
    "UnsupportedMethodError",
    "VolatilityView",
    "aggregate_completed_bars",
    "default_feature_config",
    "detect_swing_bos",
    "detect_swing_bos_series",
    "ensure_utc",
    "load_feature_config",
    "prepare_causal_bars",
]
