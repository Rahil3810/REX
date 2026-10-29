"""Automatic zone generation package (research V1)."""

from core.zones.auto.candidates import (
    SwingClusterZoneGeneratorV1,
    ZoneCandidateGenerator,
    deterministic_zone_id,
    ranking_strength_v1,
)
from core.zones.auto.config import METHOD_SWING_CLUSTER_ZONE_V1, SwingClusterZoneConfig
from core.zones.auto.evidence import (
    AutomaticZone,
    ZoneEvidence,
    ZoneLifecycleStatus,
)
from core.zones.auto.generated import GeneratedZone, ZoneGenerator
from core.zones.auto.generator import AutomaticZoneGenerator
from core.zones.auto.ma_confluence import (
    GENERATOR_VERSION as MA_CONFLUENCE_GENERATOR_VERSION,
    METHOD_MA_CONFLUENCE_ZONE_V1,
    MAConfluenceEvidence,
    MAConfluenceStatus,
    MAConfluenceZoneConfig,
    MAConfluenceZoneGenerator,
    compute_zone_bounds,
    deterministic_ma_zone_id,
)

GENERATOR_VERSION = MA_CONFLUENCE_GENERATOR_VERSION

__all__ = [
    "GENERATOR_VERSION",
    "METHOD_MA_CONFLUENCE_ZONE_V1",
    "METHOD_SWING_CLUSTER_ZONE_V1",
    "AutomaticZone",
    "AutomaticZoneGenerator",
    "GeneratedZone",
    "MAConfluenceEvidence",
    "MAConfluenceStatus",
    "MAConfluenceZoneConfig",
    "MAConfluenceZoneGenerator",
    "SwingClusterZoneConfig",
    "SwingClusterZoneGeneratorV1",
    "ZoneCandidateGenerator",
    "ZoneEvidence",
    "ZoneGenerator",
    "ZoneLifecycleStatus",
    "compute_zone_bounds",
    "deterministic_ma_zone_id",
    "deterministic_zone_id",
    "ranking_strength_v1",
]
