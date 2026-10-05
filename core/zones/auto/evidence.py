"""Evidence and lifecycle types for automatic zones (separate from canonical Zone)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from models.zone import Zone


class ZoneLifecycleStatus(StrEnum):
    """Causal lifecycle of an automatic zone as of an evaluation bar.

    - ``fresh``: no close has entered the band yet
    - ``tested``: at least one close entered the band; not broken
    - ``broken``: a close strictly beyond the structural side of the band
    """

    FRESH = "fresh"
    TESTED = "tested"
    BROKEN = "broken"


@dataclass(frozen=True)
class ZoneEvidence:
    """Raw observable evidence for an automatic zone (not a score)."""

    method_id: str
    origin_swing_id: str
    origin_index: int
    origin_timestamp: datetime
    origin_confirmation_index: int
    origin_confirmation_time: datetime
    contributing_swing_ids: tuple[str, ...]
    contributing_swing_count: int
    touch_count: int
    mitigation_count: int
    status: ZoneLifecycleStatus
    zone_age_bars: int
    departure_move: float | None
    reaction_magnitude: float | None
    bos_associated: bool
    atr_used: float | None
    cluster_tolerance: float
    asof_index: int
    asof_time: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "origin_swing_id": self.origin_swing_id,
            "origin_index": self.origin_index,
            "origin_timestamp": self.origin_timestamp.isoformat(),
            "origin_confirmation_index": self.origin_confirmation_index,
            "origin_confirmation_time": self.origin_confirmation_time.isoformat(),
            "contributing_swing_ids": list(self.contributing_swing_ids),
            "contributing_swing_count": self.contributing_swing_count,
            "touch_count": self.touch_count,
            "mitigation_count": self.mitigation_count,
            "status": self.status.value,
            "zone_age_bars": self.zone_age_bars,
            "departure_move": self.departure_move,
            "reaction_magnitude": self.reaction_magnitude,
            "bos_associated": self.bos_associated,
            "atr_used": self.atr_used,
            "cluster_tolerance": self.cluster_tolerance,
            "asof_index": self.asof_index,
            "asof_time": self.asof_time.isoformat(),
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> ZoneEvidence:
        return ZoneEvidence(
            method_id=str(payload["method_id"]),
            origin_swing_id=str(payload["origin_swing_id"]),
            origin_index=int(payload["origin_index"]),  # type: ignore[arg-type]
            origin_timestamp=datetime.fromisoformat(str(payload["origin_timestamp"])),
            origin_confirmation_index=int(payload["origin_confirmation_index"]),  # type: ignore[arg-type]
            origin_confirmation_time=datetime.fromisoformat(
                str(payload["origin_confirmation_time"])
            ),
            contributing_swing_ids=tuple(
                str(item) for item in payload["contributing_swing_ids"]  # type: ignore[index]
            ),
            contributing_swing_count=int(payload["contributing_swing_count"]),  # type: ignore[arg-type]
            touch_count=int(payload["touch_count"]),  # type: ignore[arg-type]
            mitigation_count=int(payload["mitigation_count"]),  # type: ignore[arg-type]
            status=ZoneLifecycleStatus(str(payload["status"])),
            zone_age_bars=int(payload["zone_age_bars"]),  # type: ignore[arg-type]
            departure_move=(
                None
                if payload.get("departure_move") is None
                else float(payload["departure_move"])  # type: ignore[arg-type]
            ),
            reaction_magnitude=(
                None
                if payload.get("reaction_magnitude") is None
                else float(payload["reaction_magnitude"])  # type: ignore[arg-type]
            ),
            bos_associated=bool(payload["bos_associated"]),
            atr_used=(
                None
                if payload.get("atr_used") is None
                else float(payload["atr_used"])  # type: ignore[arg-type]
            ),
            cluster_tolerance=float(payload["cluster_tolerance"]),  # type: ignore[arg-type]
            asof_index=int(payload["asof_index"]),  # type: ignore[arg-type]
            asof_time=datetime.fromisoformat(str(payload["asof_time"])),
        )


@dataclass(frozen=True)
class AutomaticZone:
    """Canonical Zone plus separated evidence and transparent ranking strength."""

    zone: Zone
    evidence: ZoneEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone.to_dict(),
            "evidence": self.evidence.to_dict(),
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> AutomaticZone:
        return AutomaticZone(
            zone=Zone.from_dict(payload["zone"]),  # type: ignore[arg-type]
            evidence=ZoneEvidence.from_dict(payload["evidence"]),  # type: ignore[arg-type]
        )
