"""Support and resistance zone models.

Canonical zone contract (P1-7 + automatic provenance):
- ``id``: deterministic identity within a symbol ZoneBook (config integer or
  generator-stable hash; not a UUID).
- ``low`` / ``high``: inclusive price bounds (``low < high`` enforced at load time).
- ``timeframe``: zone timeframe label (e.g. H1, daily, weekly, M15).
- ``source``: provenance — ``manual`` or ``automatic``.
- ``strength``: 0–10 ranking integer.
  Manual: trader rating. Automatic: transparent V1 ranking heuristic — never
  confidence/probability.
- ``kind``: optional supply/demand role for Strategy V1 HTF filters.

Manual/configured zones are static annotations. They have no detection or
confirmation timestamp; observability is not gated by market-structure causality.
Automatic zones are produced by research generators and carry evidence separately
from this canonical record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ZoneKind(Enum):
    """Semantic role of a zone for supply/demand strategies."""

    SUPPLY = "supply"
    DEMAND = "demand"


class ZoneSource(Enum):
    """Provenance of a zone entering the feature / market-state pipeline.

    ``MANUAL`` — trader/config annotations (static; no confirmation timing).
    ``AUTOMATIC`` — research generators (e.g. swing-cluster V1); causal/as-of aware.
    """

    MANUAL = "manual"
    AUTOMATIC = "automatic"


@dataclass(frozen=True)
class Zone:
    """A support/resistance area with explicit provenance."""

    id: int
    name: str
    low: float
    high: float
    timeframe: str
    strength: int
    kind: ZoneKind | None = None
    source: ZoneSource = ZoneSource.MANUAL

    def contains_price(self, price: float) -> bool:
        """Return True when price lies inside the zone boundaries."""
        return self.low <= price <= self.high

    def overlaps_bar(self, low: float, high: float) -> bool:
        """Return True when a bar's range overlaps the zone."""
        return high >= self.low and low <= self.high

    def identity_key(self, symbol: str) -> str:
        """Deterministic identity across repeated materialization for ``symbol``."""
        return f"{symbol}:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "low": self.low,
            "high": self.high,
            "timeframe": self.timeframe,
            "strength": self.strength,
            "kind": self.kind.value if isinstance(self.kind, ZoneKind) else self.kind,
            "source": self.source.value,
        }

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> Zone:
        """Reconstruct a Zone; missing ``source`` defaults to manual (legacy payloads)."""
        kind_raw = payload.get("kind")
        kind: ZoneKind | None
        if kind_raw is None:
            kind = None
        elif isinstance(kind_raw, ZoneKind):
            kind = kind_raw
        else:
            kind = ZoneKind(str(kind_raw).strip().lower())

        source_raw = payload.get("source", ZoneSource.MANUAL.value)
        if isinstance(source_raw, ZoneSource):
            source = source_raw
        else:
            source = ZoneSource(str(source_raw).strip().lower())

        return Zone(
            id=int(payload["id"]),
            name=str(payload["name"]),
            low=float(payload["low"]),
            high=float(payload["high"]),
            timeframe=str(payload["timeframe"]),
            strength=int(payload["strength"]),
            kind=kind,
            source=source,
        )


@dataclass(frozen=True)
class ZoneBook:
    """All zones for a single trading symbol."""

    symbol: str
    zones: tuple[Zone, ...]

    def get_zone(self, zone_id: int) -> Zone | None:
        """Return a zone by id, or None if not found."""
        for zone in self.zones:
            if zone.id == zone_id:
                return zone
        return None
