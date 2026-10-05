"""Zone data providers — sources of zones without detection logic."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from core.zone_loader import load_zones
from models.zone import Zone, ZoneBook, ZoneSource


class ZoneProvider(Protocol):
    """
    Supplies zones for symbols.

    Implementations may load manual config or supply research-generated zones.
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


class AutomaticZoneProvider:
    """Zones produced by AutomaticZoneGenerator (research snapshots).

    Holds already-generated ``Zone`` objects with ``source=AUTOMATIC``.
    Does not run detection itself — generation stays in AutomaticZoneGenerator.
    """

    def __init__(self, zone_books: Mapping[str, ZoneBook]) -> None:
        for book in zone_books.values():
            for zone in book.zones:
                if zone.source is not ZoneSource.AUTOMATIC:
                    raise ValueError(
                        f"AutomaticZoneProvider requires source=automatic; "
                        f"got {zone.source.value} for zone id={zone.id}"
                    )
        self._books = dict(zone_books)

    @classmethod
    def from_zones(cls, symbol: str, zones: Sequence[Zone]) -> "AutomaticZoneProvider":
        return cls({symbol: ZoneBook(symbol=symbol, zones=tuple(zones))})

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._books))

    def zones_for(self, symbol: str) -> tuple[Zone, ...]:
        book = self._books.get(symbol)
        if book is None:
            return ()
        return book.zones


class CompositeZoneProvider:
    """Concatenate zones from multiple providers (manual + automatic, etc.)."""

    def __init__(self, providers: Sequence[ZoneProvider]) -> None:
        self._providers = tuple(providers)

    def symbols(self) -> tuple[str, ...]:
        names: set[str] = set()
        for provider in self._providers:
            names.update(provider.symbols())
        return tuple(sorted(names))

    def zones_for(self, symbol: str) -> tuple[Zone, ...]:
        zones: list[Zone] = []
        for provider in self._providers:
            zones.extend(provider.zones_for(symbol))
        return tuple(zones)
