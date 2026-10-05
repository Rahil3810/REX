"""Load manually maintained support/resistance zones from config/zones.json."""

import json
from pathlib import Path

from core.validation import ConfigurationError, validate_zone_entries
from models.zone import Zone, ZoneBook, ZoneKind, ZoneSource


def load_zones(config_path: Path) -> dict[str, ZoneBook]:
    """
    Load zone definitions from a JSON file.

    Zones are never calculated automatically — they must be defined by the trader
    in config/zones.json. Every loaded zone is tagged ``source=manual``.
    Optional ``kind`` is ``supply`` or ``demand`` (Strategy V1 HTF).

    Expected format:
        {
          "EURUSD": {
            "zones": [
              {
                "id": 1,
                "name": "weekly_demand",
                "low": 1.1500,
                "high": 1.1520,
                "timeframe": "weekly",
                "strength": 9,
                "kind": "demand"
              }
            ]
          }
        }
    """
    with config_path.open(encoding="utf-8") as file:
        raw = json.load(file)

    if not isinstance(raw, dict):
        raise ConfigurationError("Zone configuration root must be a JSON object")

    zone_books: dict[str, ZoneBook] = {}

    for symbol, symbol_data in raw.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise ConfigurationError("Zone configuration contains an invalid symbol")
        if not isinstance(symbol_data, dict):
            raise ConfigurationError(f"Zone data for {symbol} must be an object")
        entries = symbol_data.get("zones", [])
        validate_zone_entries(symbol, entries)
        zones = tuple(
            Zone(
                id=entry["id"],
                name=entry["name"],
                low=entry["low"],
                high=entry["high"],
                timeframe=entry.get("timeframe", ""),
                strength=entry.get("strength", 0),
                kind=_parse_zone_kind(entry.get("kind")),
                source=_parse_zone_source(entry.get("source")),
            )
            for entry in entries
        )
        zone_books[symbol] = ZoneBook(symbol=symbol, zones=zones)

    return zone_books


def _parse_zone_kind(raw: object) -> ZoneKind | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    return ZoneKind(raw.strip().lower())


def _parse_zone_source(raw: object) -> ZoneSource:
    """Config zones are manual; optional explicit ``source`` must be manual."""
    if raw is None:
        return ZoneSource.MANUAL
    if not isinstance(raw, str):
        raise ConfigurationError("Zone source must be a string when provided")
    try:
        source = ZoneSource(raw.strip().lower())
    except ValueError as exc:
        raise ConfigurationError(
            f"Unsupported zone source {raw!r}; config zones must be 'manual'"
        ) from exc
    if source is not ZoneSource.MANUAL:
        raise ConfigurationError(
            f"Config zones cannot use source={raw!r}; only 'manual' is allowed"
        )
    return source
