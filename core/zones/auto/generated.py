"""Swing-free zone generator contract for research automatic zones.

Parallel to ``ZoneCandidateGenerator`` (which requires swings). Strategies
consume only canonical ``Zone`` / ``ZoneBook``; evidence stays method-specific.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from models.bar import Bar
from models.zone import Zone


@dataclass(frozen=True)
class GeneratedZone:
    """Canonical Zone plus opaque method-specific evidence."""

    zone: Zone
    evidence: Any

    def to_dict(self) -> dict[str, Any]:
        evidence = self.evidence
        evidence_payload = (
            evidence.to_dict() if hasattr(evidence, "to_dict") else evidence
        )
        return {
            "zone": self.zone.to_dict(),
            "evidence": evidence_payload,
        }


class ZoneGenerator(Protocol):
    """Causal zone discovery that does not require swing events."""

    method_id: str

    def generate(
        self,
        bars: Sequence[Bar],
        *,
        timeframe: str,
        asof_index: int,
        asof_time: datetime,
    ) -> tuple[GeneratedZone, ...]:
        """Produce zones using only information available at asof."""
        ...
