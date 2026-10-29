"""Reusable zone engine (manual + automatic providers; provider-swappable)."""

from core.zones.auto import (
    METHOD_MA_CONFLUENCE_ZONE_V1,
    METHOD_SWING_CLUSTER_ZONE_V1,
    AutomaticZone,
    AutomaticZoneGenerator,
    GeneratedZone,
    MAConfluenceEvidence,
    MAConfluenceStatus,
    MAConfluenceZoneConfig,
    MAConfluenceZoneGenerator,
    SwingClusterZoneConfig,
    SwingClusterZoneGeneratorV1,
    ZoneEvidence,
    ZoneLifecycleStatus,
)
from core.zones.engine import ZoneEngine
from core.zones.evaluation import (
    METHOD_ZONE_EVAL_V1,
    InteractionOutcome,
    ZoneEvaluation,
    ZoneEvaluationConfig,
    ZoneEvaluationSubject,
    ZoneEvaluator,
    ZoneInteractionEvaluation,
)
from core.zones.providers import (
    AutomaticZoneProvider,
    CompositeZoneProvider,
    ManualZoneProvider,
    ZoneProvider,
)
from core.zones.types import (
    SUPPORTED_HTF_KINDS,
    SUPPORTED_HTF_TIMEFRAMES,
    ZoneDistance,
    is_supported_htf_zone,
    normalize_zone_timeframe,
    select_preferred_inside_zone,
)
from models.zone import ZoneKind, ZoneSource

__all__ = [
    "METHOD_MA_CONFLUENCE_ZONE_V1",
    "METHOD_SWING_CLUSTER_ZONE_V1",
    "METHOD_ZONE_EVAL_V1",
    "AutomaticZone",
    "AutomaticZoneGenerator",
    "AutomaticZoneProvider",
    "CompositeZoneProvider",
    "GeneratedZone",
    "InteractionOutcome",
    "MAConfluenceEvidence",
    "MAConfluenceStatus",
    "MAConfluenceZoneConfig",
    "MAConfluenceZoneGenerator",
    "ManualZoneProvider",
    "SUPPORTED_HTF_KINDS",
    "SUPPORTED_HTF_TIMEFRAMES",
    "SwingClusterZoneConfig",
    "SwingClusterZoneGeneratorV1",
    "ZoneDistance",
    "ZoneEngine",
    "ZoneEvaluation",
    "ZoneEvaluationConfig",
    "ZoneEvaluationSubject",
    "ZoneEvaluator",
    "ZoneEvidence",
    "ZoneInteractionEvaluation",
    "ZoneKind",
    "ZoneLifecycleStatus",
    "ZoneProvider",
    "ZoneSource",
    "is_supported_htf_zone",
    "normalize_zone_timeframe",
    "select_preferred_inside_zone",
]
