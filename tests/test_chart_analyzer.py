"""Tests for the chart analyzer."""

import unittest

from core.chart_analyzer import ChartAnalyzer
from core.market import distance_to_pips_for_symbol, pip_size_for_symbol
from models.zone import Zone, ZoneBook


class ChartAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zone_book = ZoneBook(
            symbol="EURUSD",
            zones=(
                Zone(
                    id=1,
                    name="weekly_support",
                    low=1.1500,
                    high=1.1520,
                    timeframe="weekly",
                    strength=9,
                ),
                Zone(
                    id=2,
                    name="daily_resistance",
                    low=1.1650,
                    high=1.1670,
                    timeframe="daily",
                    strength=7,
                ),
                Zone(
                    id=3,
                    name="weekly_resistance",
                    low=1.1700,
                    high=1.1720,
                    timeframe="weekly",
                    strength=8,
                ),
            ),
        )
        self.analyzer = ChartAnalyzer()

    def test_current_price_and_inside_zone(self) -> None:
        context = self.analyzer.analyze(self.zone_book, 1.1510)

        self.assertEqual(context.symbol, "EURUSD")
        self.assertEqual(context.current_price, 1.1510)
        self.assertTrue(context.inside_zone)
        self.assertEqual(context.active_zone_id, 1)
        self.assertEqual(context.active_zone_name, "weekly_support")
        self.assertEqual(context.active_zone_strength, 9)
        self.assertEqual(context.active_zone_timeframe, "weekly")

    def test_nearest_zone_above(self) -> None:
        context = self.analyzer.analyze(self.zone_book, 1.1582)

        self.assertFalse(context.inside_zone)
        self.assertIsNotNone(context.nearest_zone_above)
        assert context.nearest_zone_above is not None
        self.assertEqual(context.nearest_zone_above.id, 2)
        self.assertAlmostEqual(context.nearest_zone_above.distance_pips, 68.0)

    def test_nearest_zone_below(self) -> None:
        context = self.analyzer.analyze(self.zone_book, 1.1582)

        self.assertIsNotNone(context.nearest_zone_below)
        assert context.nearest_zone_below is not None
        self.assertEqual(context.nearest_zone_below.id, 1)
        self.assertAlmostEqual(context.nearest_zone_below.distance_pips, 62.0)

    def test_market_context_to_dict(self) -> None:
        context = self.analyzer.analyze(self.zone_book, 1.1582)
        payload = context.to_dict()

        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["current_price"], 1.1582)
        self.assertFalse(payload["inside_zone"])
        self.assertIsNotNone(payload["nearest_zone_above"])
        self.assertIsNotNone(payload["nearest_zone_below"])

    def test_pip_size_eurusd(self) -> None:
        self.assertEqual(pip_size_for_symbol("EURUSD"), 0.0001)

    def test_pip_size_xauusd(self) -> None:
        self.assertEqual(pip_size_for_symbol("XAUUSD"), 0.1)

    def test_price_to_pips(self) -> None:
        self.assertEqual(distance_to_pips_for_symbol(0.0010, "EURUSD"), 10.0)


if __name__ == "__main__":
    unittest.main()
