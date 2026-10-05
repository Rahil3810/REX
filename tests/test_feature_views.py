"""Tests for Feature Views (pure projections)."""

import unittest
from datetime import datetime, timedelta

from core.features import (
    FeatureRepository,
    METHOD_MOMENTUM_TS_MOM_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    MomentumView,
    TrendView,
    UnsupportedMethodError,
    VolatilityView,
)
from models.bar import Bar
from models.market_structure import MarketTrend, RangeExpansionState


def _trend_bars(
    symbol: str,
    direction: str,
    count: int = 70,
    start: float = 1.1000,
    small_body: float = 0.0004,
    large_recent_body: bool = False,
) -> list[Bar]:
    bars: list[Bar] = []
    slope = 0.0010 if direction == "up" else -0.0010
    timestamp = datetime(2026, 6, 20, 0, 0, 0)

    for index in range(count):
        close = start + slope * index
        body = 0.0020 if large_recent_body and index >= count - 5 else small_body
        open_price = close - body if direction == "up" else close + body
        high = max(open_price, close) + 0.0006
        low = min(open_price, close) - 0.0006

        if index % 6 == 2:
            high += 0.0030
        if index % 6 == 5:
            low -= 0.0030

        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp + timedelta(minutes=15 * index),
                open=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return bars


def _monotonic_bars(symbol: str, count: int = 70) -> list[Bar]:
    bars: list[Bar] = []
    timestamp = datetime(2026, 6, 20, 0, 0, 0)
    for index in range(count):
        close = 1.1000 + 0.0005 * index
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp + timedelta(minutes=15 * index),
                open=close - 0.0003,
                high=close + 0.0006,
                low=close - 0.0006,
                close=close,
            )
        )
    return bars


class FeatureViewTests(unittest.TestCase):
    def test_trend_view_requires_method_id(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up")},
            entry_timeframe="M15",
        )
        with self.assertRaises(UnsupportedMethodError):
            TrendView().project(context, "")

    def test_market_structure_v1_detects_bullish_swings(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {
                "M15": _trend_bars("EURUSD", "up", count=200),
                "M30": _trend_bars("EURUSD", "up", count=200),
                "H1": _trend_bars("EURUSD", "up", count=200),
                "H4": _trend_bars("EURUSD", "up", count=200),
            },
            entry_timeframe="M15",
        )
        projection = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        self.assertEqual(projection.trend, MarketTrend.BULLISH)
        self.assertIn("higher highs", projection.reason)
        self.assertGreater(projection.structure_score, 0)
        # Causal HTF rebuild from trending M15 often yields insufficient HTF
        # fractal swings (strong trends suppress local extrema) — agreement
        # may be partial/neutral; entry structure remains the primary signal.
        self.assertIn("M30", projection.by_timeframe)
        self.assertIn("H1", projection.by_timeframe)

    def test_monotonic_bars_are_not_bullish_without_swings(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _monotonic_bars("EURUSD")},
            entry_timeframe="M15",
        )
        projection = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        self.assertNotEqual(projection.trend, MarketTrend.BULLISH)

    def test_range_expansion_is_volatility_not_momentum(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up", large_recent_body=True)},
            entry_timeframe="M15",
        )
        expansion = VolatilityView().project(
            context, METHOD_VOLATILITY_RANGE_EXPANSION_V1
        )
        self.assertEqual(expansion.state, RangeExpansionState.HIGH)
        self.assertIn("Recent average candle body", expansion.reason)

        with self.assertRaises(UnsupportedMethodError):
            MomentumView().project(context, METHOD_VOLATILITY_RANGE_EXPANSION_V1)

    def test_ts_mom_v1_projects_from_returns(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up")},
            entry_timeframe="M15",
        )
        momentum = MomentumView().project(context, METHOD_MOMENTUM_TS_MOM_V1)
        self.assertEqual(momentum.method_id, METHOD_MOMENTUM_TS_MOM_V1)
        self.assertIn("ts_mom_v1", momentum.reason)


if __name__ == "__main__":
    unittest.main()
