"""Tests for signal enrichment."""

import unittest
from datetime import datetime

from core.chart_analyzer import ChartAnalyzer
from core.signal_enricher import enrich_signal
from models.signal import Signal, SignalType
from models.zone import Zone, ZoneBook


class SignalEnricherTests(unittest.TestCase):
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

    def test_enrich_break_above_signal(self) -> None:
        raw_signal = Signal(
            symbol="EURUSD",
            signal=SignalType.BREAK_ABOVE,
            zone_id=2,
            price=1.1675,
            timestamp=datetime(2026, 6, 20, 12, 0, 0),
            reason="Price broke above zone 'daily_resistance' at 1.167",
        )
        context = self.analyzer.analyze(self.zone_book, 1.1675)
        enriched = enrich_signal(raw_signal, context, self.zone_book)

        self.assertTrue(enriched.is_enriched)
        self.assertEqual(enriched.nearest_zone_above, 3)
        self.assertIsNotNone(enriched.distance_to_zone_above)
        self.assertIsNotNone(enriched.market_context_summary)
        self.assertIn("daily_resistance", enriched.market_context_summary)

    def test_enriched_to_dict_includes_context_fields(self) -> None:
        raw_signal = Signal(
            symbol="EURUSD",
            signal=SignalType.BREAK_ABOVE,
            zone_id=2,
            price=1.1675,
            timestamp=datetime(2026, 6, 20, 12, 0, 0),
            reason="test",
        )
        context = self.analyzer.analyze(self.zone_book, 1.1675)
        enriched = enrich_signal(raw_signal, context, self.zone_book)
        payload = enriched.to_dict()

        self.assertIn("nearest_zone_above", payload)
        self.assertIn("distance_to_zone_above", payload)
        self.assertIn("market_context_summary", payload)

    def test_unenriched_signal_preserves_base_format(self) -> None:
        signal = Signal(
            symbol="EURUSD",
            signal=SignalType.ENTER_ZONE,
            zone_id=1,
            price=1.1510,
            timestamp=datetime(2026, 6, 20, 12, 0, 0),
            reason="test",
        )
        payload = signal.to_dict()

        self.assertEqual(
            set(payload.keys()),
            {"symbol", "signal", "zone_id", "price", "timestamp", "reason"},
        )


if __name__ == "__main__":
    unittest.main()
