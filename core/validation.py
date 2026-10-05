"""Configuration validation shared by loaders and application entry points."""

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Protocol

from models.zone import ZoneBook, ZoneKind, ZoneSource

VALID_PAIR_TIMEFRAMES = frozenset(
    {
        "M5",
        "m5",
        "5m",
        "M15",
        "m15",
        "15m",
        "H1",
        "h1",
        "1h",
        "H4",
        "h4",
        "4h",
    }
)
VALID_ZONE_TIMEFRAMES = frozenset(
    {
        "M5",
        "m5",
        "5m",
        "M15",
        "m15",
        "15m",
        "H1",
        "h1",
        "1h",
        "H4",
        "h4",
        "4h",
        "daily",
        "weekly",
        "monthly",
    }
)


class ConfigurationError(ValueError):
    """Base class for actionable configuration failures."""


class DuplicateZoneIdError(ConfigurationError):
    pass


class InvalidZoneError(ConfigurationError):
    pass


class OverlappingZoneError(ConfigurationError):
    pass


class MissingPairConfigurationError(ConfigurationError):
    pass


class InvalidTimeframeError(ConfigurationError):
    pass


class PairLike(Protocol):
    symbol: str
    base_timeframe: str


def validate_pair_entries(entries: object) -> None:
    if not isinstance(entries, list):
        raise ConfigurationError("'pairs' must be a JSON array")

    seen_symbols: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigurationError(f"Pair entry {index} must be an object")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ConfigurationError(f"Pair entry {index} has no valid symbol")
        if symbol in seen_symbols:
            raise ConfigurationError(f"Duplicate pair configuration: {symbol}")
        seen_symbols.add(symbol)
        timeframe = entry.get("base_timeframe", "15m")
        if timeframe not in VALID_PAIR_TIMEFRAMES:
            raise InvalidTimeframeError(
                f"Invalid timeframe '{timeframe}' for {symbol}. "
                f"Supported: {sorted(VALID_PAIR_TIMEFRAMES)}"
            )


def validate_zone_entries(symbol: str, entries: object) -> None:
    if not isinstance(entries, list):
        raise InvalidZoneError(f"Zones for {symbol} must be a JSON array")

    seen_ids: set[int] = set()
    normalized: list[tuple[int, float, float]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InvalidZoneError(f"Zone {index} for {symbol} must be an object")

        zone_id = entry.get("id")
        if not isinstance(zone_id, int) or isinstance(zone_id, bool) or zone_id <= 0:
            raise InvalidZoneError(
                f"Zone {index} for {symbol} must have a positive integer id"
            )
        if zone_id in seen_ids:
            raise DuplicateZoneIdError(
                f"Duplicate zone id {zone_id} for {symbol}"
            )
        seen_ids.add(zone_id)

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise InvalidZoneError(f"Zone {zone_id} for {symbol} has no valid name")

        low = entry.get("low")
        high = entry.get("high")
        if (
            not isinstance(low, (int, float))
            or isinstance(low, bool)
            or not isinstance(high, (int, float))
            or isinstance(high, bool)
            or not isfinite(float(low))
            or not isfinite(float(high))
            or float(low) >= float(high)
        ):
            raise InvalidZoneError(
                f"Zone {zone_id} for {symbol} requires finite low < high"
            )

        timeframe = entry.get("timeframe", "")
        if timeframe not in VALID_ZONE_TIMEFRAMES:
            raise InvalidTimeframeError(
                f"Invalid zone timeframe '{timeframe}' for {symbol} zone {zone_id}"
            )

        strength = entry.get("strength", 0)
        if (
            not isinstance(strength, int)
            or isinstance(strength, bool)
            or not 0 <= strength <= 10
        ):
            raise InvalidZoneError(
                f"Zone {zone_id} for {symbol} strength must be an integer from 0 to 10"
            )

        kind = entry.get("kind")
        if kind is not None:
            if not isinstance(kind, str):
                raise InvalidZoneError(
                    f"Zone {zone_id} for {symbol} kind must be a string when provided"
                )
            try:
                ZoneKind(kind.strip().lower())
            except ValueError as exc:
                raise InvalidZoneError(
                    f"Zone {zone_id} for {symbol} kind must be "
                    f"'supply' or 'demand', got {kind!r}"
                ) from exc

        source = entry.get("source")
        if source is not None:
            if not isinstance(source, str):
                raise InvalidZoneError(
                    f"Zone {zone_id} for {symbol} source must be a string when provided"
                )
            try:
                parsed = ZoneSource(source.strip().lower())
            except ValueError as exc:
                raise InvalidZoneError(
                    f"Zone {zone_id} for {symbol} source must be "
                    f"'manual' or 'automatic', got {source!r}"
                ) from exc
            if parsed is not ZoneSource.MANUAL:
                raise InvalidZoneError(
                    f"Zone {zone_id} for {symbol}: config/zones.json may only use "
                    f"source='manual' (got {source!r})"
                )

        normalized.append((zone_id, float(low), float(high)))

    for position, (zone_id, low, high) in enumerate(normalized):
        for other_id, other_low, other_high in normalized[position + 1 :]:
            if high >= other_low and other_high >= low:
                raise OverlappingZoneError(
                    f"Zones {zone_id} and {other_id} overlap for {symbol}"
                )


def validate_configuration_coverage(
    pairs: Iterable[PairLike],
    zone_books: Mapping[str, ZoneBook],
) -> None:
    """Ensure every zone book belongs to a configured pair."""
    configured = {pair.symbol for pair in pairs}
    missing = sorted(set(zone_books) - configured)
    if missing:
        raise MissingPairConfigurationError(
            "Zone configuration has no matching pair configuration for: "
            + ", ".join(missing)
        )
