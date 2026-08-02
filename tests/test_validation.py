"""Tests for pair and zone configuration validation."""

import unittest
from dataclasses import dataclass

from core.validation import (
    DuplicateZoneIdError,
    InvalidTimeframeError,
    InvalidZoneError,
    MissingPairConfigurationError,
    OverlappingZoneError,
    validate_configuration_coverage,
    validate_pair_entries,
    validate_zone_entries,
)
from models.zone import ZoneBook


def valid_zone(zone_id: int, low: float, high: float) -> dict[str, object]:
    return {
        "id": zone_id,
        "name": f"zone_{zone_id}",
        "low": low,
        "high": high,
        "timeframe": "daily",
        "strength": 5,
    }


@dataclass(frozen=True)
class Pair:
    symbol: str
    base_timeframe: str = "15m"


class ValidationTests(unittest.TestCase):
    def test_duplicate_zone_ids(self) -> None:
        with self.assertRaises(DuplicateZoneIdError):
            validate_zone_entries(
                "EURUSD",
                [valid_zone(1, 1.1, 1.2), valid_zone(1, 1.3, 1.4)],
            )

    def test_invalid_and_overlapping_zones(self) -> None:
        with self.assertRaises(InvalidZoneError):
            validate_zone_entries("EURUSD", [valid_zone(1, 1.2, 1.1)])
        with self.assertRaises(OverlappingZoneError):
            validate_zone_entries(
                "EURUSD",
                [valid_zone(1, 1.1, 1.2), valid_zone(2, 1.19, 1.3)],
            )

    def test_invalid_pair_timeframe(self) -> None:
        with self.assertRaises(InvalidTimeframeError):
            validate_pair_entries(
                [{"symbol": "EURUSD", "base_timeframe": "D7"}]
            )

    def test_missing_pair_configuration(self) -> None:
        with self.assertRaises(MissingPairConfigurationError):
            validate_configuration_coverage(
                [Pair("EURUSD")],
                {"XAUUSD": ZoneBook(symbol="XAUUSD", zones=())},
            )


if __name__ == "__main__":
    unittest.main()

