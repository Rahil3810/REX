"""Support and resistance zone models."""

from dataclasses import dataclass
from enum import Enum


class ZoneKind(Enum):
    """Semantic role of a zone for supply/demand strategies."""

    SUPPLY = "supply"
    DEMAND = "demand"


@dataclass(frozen=True)
class Zone:
    """A manually maintained support or resistance area."""

    id: int
    name: str
    low: float
    high: float
    timeframe: str
    strength: int
    kind: ZoneKind | None = None

    def contains_price(self, price: float) -> bool:
        """Return True when price lies inside the zone boundaries."""
        return self.low <= price <= self.high

    def overlaps_bar(self, low: float, high: float) -> bool:
        """Return True when a bar's range overlaps the zone."""
        return high >= self.low and low <= self.high


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
