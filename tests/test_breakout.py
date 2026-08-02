"""Tests for the breakout strategy."""

import unittest
from datetime import datetime

from models.bar import Bar
from models.signal import SignalType
from models.zone import Zone, ZoneBook
from strategies.breakout import BreakoutStrategy


def _make_bar(symbol: str, close: float, low: float, high: float) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 6, 20, 12, 0, 0),
        open=close,
        high=high,
        low=low,
        close=close,
    )


class BreakoutStrategyTests(unittest.TestCase):
    def test_enter_zone(self) -> None:
        zone_book = ZoneBook(
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
            ),
        )
        strategy = BreakoutStrategy(zone_book=zone_book)

        strategy.evaluate(_make_bar("EURUSD", 1.1490, 1.1485, 1.1495))
        signals = strategy.evaluate(_make_bar("EURUSD", 1.1510, 1.1505, 1.1515))

        enter_signals = [s for s in signals if s.signal == SignalType.ENTER_ZONE]
        self.assertEqual(len(enter_signals), 1)
        self.assertEqual(enter_signals[0].zone_id, 1)

    def test_break_above(self) -> None:
        zone_book = ZoneBook(
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
            ),
        )
        strategy = BreakoutStrategy(zone_book=zone_book)

        strategy.evaluate(_make_bar("EURUSD", 1.1510, 1.1505, 1.1515))
        signals = strategy.evaluate(_make_bar("EURUSD", 1.1530, 1.1515, 1.1535))

        break_signals = [s for s in signals if s.signal == SignalType.BREAK_ABOVE]
        self.assertEqual(len(break_signals), 1)

    def test_signal_to_dict_format(self) -> None:
        zone_book = ZoneBook(
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
            ),
        )
        strategy = BreakoutStrategy(zone_book=zone_book)
        signals = strategy.evaluate(_make_bar("EURUSD", 1.1510, 1.1505, 1.1515))

        payload = signals[0].to_dict()
        self.assertEqual(
            set(payload.keys()),
            {"symbol", "signal", "zone_id", "price", "timestamp", "reason"},
        )
        self.assertTrue(all(isinstance(value, str) for value in payload.values()))


if __name__ == "__main__":
    unittest.main()
