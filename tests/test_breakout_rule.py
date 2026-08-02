"""Tests for the standalone breakout rule."""

import unittest
from datetime import datetime

from models.bar import Bar
from models.zone import Zone
from strategies.breakout import PricePosition
from strategies.rules.breakout_rule import BreakoutRule


def _make_bar(close: float, low: float, high: float) -> Bar:
    return Bar(
        symbol="EURUSD",
        timestamp=datetime(2026, 6, 20, 12, 0, 0),
        open=close,
        high=high,
        low=low,
        close=close,
    )


class BreakoutRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rule = BreakoutRule()
        self.zone = Zone(
            id=1,
            name="weekly_support",
            low=1.1500,
            high=1.1520,
            timeframe="weekly",
            strength=9,
        )

    def test_detect_break_above_first_seen_requires_touching_zone_high(self) -> None:
        self.assertTrue(
            self.rule.detect_break_above(
                _make_bar(close=1.1530, low=1.1515, high=1.1535),
                self.zone,
                None,
            )
        )
        self.assertFalse(
            self.rule.detect_break_above(
                _make_bar(close=1.1530, low=1.1525, high=1.1535),
                self.zone,
                None,
            )
        )

    def test_detect_break_above_after_state_requires_not_already_above(self) -> None:
        self.assertTrue(
            self.rule.detect_break_above(
                _make_bar(close=1.1530, low=1.1515, high=1.1535),
                self.zone,
                PricePosition.INSIDE,
            )
        )
        self.assertFalse(
            self.rule.detect_break_above(
                _make_bar(close=1.1530, low=1.1525, high=1.1535),
                self.zone,
                PricePosition.ABOVE,
            )
        )

    def test_detect_break_below_first_seen_requires_touching_zone_low(self) -> None:
        self.assertTrue(
            self.rule.detect_break_below(
                _make_bar(close=1.1490, low=1.1485, high=1.1505),
                self.zone,
                None,
            )
        )
        self.assertFalse(
            self.rule.detect_break_below(
                _make_bar(close=1.1490, low=1.1485, high=1.1495),
                self.zone,
                None,
            )
        )

    def test_detect_break_below_after_state_requires_not_already_below(self) -> None:
        self.assertTrue(
            self.rule.detect_break_below(
                _make_bar(close=1.1490, low=1.1485, high=1.1505),
                self.zone,
                PricePosition.INSIDE,
            )
        )
        self.assertFalse(
            self.rule.detect_break_below(
                _make_bar(close=1.1490, low=1.1485, high=1.1505),
                self.zone,
                PricePosition.BELOW,
            )
        )


if __name__ == "__main__":
    unittest.main()
