"""Tests for strategy discovery and placeholder behavior."""

import unittest
from datetime import datetime

from models.bar import Bar
from strategies.registry import build_default_registry


class StrategyRegistryTests(unittest.TestCase):
    def test_discovers_catalog_and_existing_strategy(self) -> None:
        registry = build_default_registry()
        self.assertTrue(
            {
                "S001",
                "S002",
                "S003",
                "S004",
                "S005",
                "S006",
                "CORE_ZONE_BREAKOUT",
            }.issubset(registry.ids())
        )

    def test_placeholder_has_metadata_and_no_logic(self) -> None:
        strategy = build_default_registry().create("S001")
        bar = Bar(
            symbol="EURUSD",
            timestamp=datetime(2026, 6, 20, 12),
            open=1.1,
            high=1.2,
            low=1.0,
            close=1.15,
        )
        self.assertEqual(strategy.strategy_name, "ZoneBreakout")
        self.assertEqual(strategy.generate_signals(bar), [])


if __name__ == "__main__":
    unittest.main()

