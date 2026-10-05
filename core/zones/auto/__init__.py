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
from core.zones.auto.generator import AutomaticZoneGenerator

__all__ = [
    "METHOD_SWING_CLUSTER_ZONE_V1",
    "AutomaticZone",
    "AutomaticZoneGenerator",
    "SwingClusterZoneConfig",
    "SwingClusterZoneGeneratorV1",
    "ZoneCandidateGenerator",
    "ZoneEvidence",
    "ZoneLifecycleStatus",
    "deterministic_zone_id",
    "ranking_strength_v1",
]
