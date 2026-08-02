"""Tests for the Strategy V1 ZoneEngine and manual provider."""

import tempfile
import unittest
from pathlib import Path

from core.zones import ManualZoneProvider, ZoneEngine, ZoneKind
from models.zone import Zone, ZoneBook


def _htf_book() -> ZoneBook:
    return ZoneBook(
        symbol="EURUSD",
        zones=(
            Zone(
                id=1,
                name="h1_noise",
                low=1.1000,
                high=1.1010,
                timeframe="H1",
                strength=5,
            ),
            Zone(
                id=2,
                name="weekly_supply",
                low=1.1200,
                high=1.1250,
                timeframe="weekly",
                strength=9,
                kind=ZoneKind.SUPPLY,
            ),
            Zone(
                id=3,
                name="weekly_demand",
                low=1.0800,
                high=1.0850,
                timeframe="weekly",
                strength=8,
                kind=ZoneKind.DEMAND,
            ),
            Zone(
                id=4,
                name="daily_supply",
                low=1.1100,
                high=1.1120,
                timeframe="daily",
                strength=7,
                kind=ZoneKind.SUPPLY,
            ),
            Zone(
                id=5,
                name="daily_demand",
                low=1.0900,
                high=1.0920,
                timeframe="D1",
                strength=7,
                kind=ZoneKind.DEMAND,
            ),
        ),
    )


class ZoneEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ZoneEngine(ManualZoneProvider.from_zone_book(_htf_book()))

    def test_htf_filter_excludes_h1_without_kind(self) -> None:
        zones = self.engine.zones("EURUSD", htf_only=True)
        self.assertEqual({z.id for z in zones}, {2, 3, 4, 5})

    def test_is_price_inside_weekly_demand(self) -> None:
        self.assertTrue(self.engine.is_price_inside_zone("EURUSD", 1.0825))
        self.assertFalse(self.engine.is_price_inside_zone("EURUSD", 1.1005))

    def test_active_zones_returns_containing_htf_zone(self) -> None:
        active = self.engine.active_zones("EURUSD", 1.1110)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "daily_supply")

    def test_distance_to_nearest_above(self) -> None:
        nearest = self.engine.distance_to_nearest_zone("EURUSD", 1.1050)
        self.assertIsNotNone(nearest)
        assert nearest is not None
        self.assertEqual(nearest.side, "above")
        self.assertEqual(nearest.zone.id, 4)
        self.assertAlmostEqual(nearest.distance_pips, 50.0)

    def test_distance_inside_is_zero(self) -> None:
        nearest = self.engine.distance_to_nearest_zone("EURUSD", 1.1220)
        self.assertIsNotNone(nearest)
        assert nearest is not None
        self.assertEqual(nearest.side, "inside")
        self.assertEqual(nearest.distance_pips, 0.0)

    def test_kind_filter(self) -> None:
        demand = self.engine.zones("EURUSD", htf_only=True, kind=ZoneKind.DEMAND)
        self.assertEqual({z.id for z in demand}, {3, 5})

    def test_provider_can_be_swapped(self) -> None:
        class StubProvider:
            def symbols(self) -> tuple[str, ...]:
                return ("XAUUSD",)

            def zones_for(self, symbol: str) -> tuple[Zone, ...]:
                if symbol != "XAUUSD":
                    return ()
                return (
                    Zone(
                        id=99,
                        name="ai_weekly_supply",
                        low=2300.0,
                        high=2310.0,
                        timeframe="weekly",
                        strength=6,
                        kind=ZoneKind.SUPPLY,
                    ),
                )

        engine = ZoneEngine(StubProvider())
        self.assertTrue(engine.is_price_inside_zone("XAUUSD", 2305.0))

    def test_manual_provider_from_config_reads_kind(self) -> None:
        payload = """
        {
          "EURUSD": {
            "zones": [
              {
                "id": 1,
                "name": "weekly_supply",
                "low": 1.2,
                "high": 1.21,
                "timeframe": "weekly",
                "strength": 9,
                "kind": "supply"
              }
            ]
          }
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.json"
            path.write_text(payload, encoding="utf-8")
            provider = ManualZoneProvider.from_config(path)
            zones = provider.zones_for("EURUSD")
            self.assertEqual(len(zones), 1)
            self.assertEqual(zones[0].kind, ZoneKind.SUPPLY)


class StrategyV1PlaceholderTests(unittest.TestCase):
    def test_structure_placeholders_are_inert(self) -> None:
        from core.market import require_instrument
        from core.market_structure import (
            PlaceholderBOSDetector,
            PlaceholderCHoCHDetector,
            PlaceholderSwingDetector,
            PlaceholderTrendStateAnalyzer,
            TrendState,
        )

        bars: tuple = ()
        instrument = require_instrument("EURUSD")
        self.assertEqual(PlaceholderSwingDetector().detect(bars), ())
        self.assertEqual(PlaceholderBOSDetector().detect(bars), ())
        self.assertEqual(PlaceholderCHoCHDetector().detect(bars), ())
        snapshot = PlaceholderTrendStateAnalyzer().analyze(bars, instrument)
        self.assertEqual(snapshot.state, TrendState.UNKNOWN)

    def test_liquidity_and_momentum_placeholders(self) -> None:
        from core.liquidity import PlaceholderLiquidityEngine
        from core.market import require_instrument
        from core.momentum import MomentumBias, PlaceholderMomentumEngine

        instrument = require_instrument("EURUSD")
        self.assertEqual(
            PlaceholderLiquidityEngine().analyze((), instrument).symbol, "EURUSD"
        )
        self.assertEqual(
            PlaceholderMomentumEngine().analyze((), instrument).bias,
            MomentumBias.UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
