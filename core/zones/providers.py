"""Zone data providers — sources of zones without detection logic."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from core.zone_loader import load_zones
from models.zone import Zone, ZoneBook


class ZoneProvider(Protocol):
    """
    Supplies zones for symbols.

    Implementations may load manual config, call an ML model, or wrap AI labels.
    Consumers (ZoneEngine) depend only on this contract — not on how zones are produced.
    """

    def symbols(self) -> tuple[str, ...]:
        """Return symbols that have at least one zone definition."""

    def zones_for(self, symbol: str) -> tuple[Zone, ...]:
        """Return all zones for a symbol (empty if unknown)."""


class ManualZoneProvider:
    """Zones defined by the trader — never auto-detected."""

    def __init__(self, zone_books: Mapping[str, ZoneBook]) -> None:
        self._books = dict(zone_books)

    @classmethod
    def from_config(cls, config_path: Path) -> "ManualZoneProvider":
        """Build a provider from ``config/zones.json`` (or equivalent)."""
        return cls(load_zones(config_path))

    @classmethod
    def from_zone_book(cls, zone_book: ZoneBook) -> "ManualZoneProvider":
        """Build a single-symbol provider."""
        return cls({zone_book.symbol: zone_book})

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._books))

    def zones_for(self, symbol: str) -> tuple[Zone, ...]:
        book = self._books.get(symbol)
        if book is None:
            return ()
        return book.zones
