"""Tests for FeatureRepository-backed market structure research path."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.features import (
    FeatureRepository,
    METHOD_PHASE_HEURISTIC_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PhaseView,
    TrendView,
    VolatilityView,
    load_feature_config,
)
from models.bar import Bar
from models.market_structure import MarketPhase, MarketTrend, RangeExpansionState


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


class FeatureMarketStructureTests(unittest.TestCase):
    def test_detects_bullish_structure_from_higher_highs_and_lows(self) -> None:
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
        trend = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        phase = PhaseView().project(context, METHOD_PHASE_HEURISTIC_V1)

        self.assertEqual(trend.trend, MarketTrend.BULLISH)
        self.assertEqual(phase.phase, MarketPhase.TREND)
        self.assertGreater(trend.structure_score, 0)
        self.assertNotIn("confidence", trend.__dataclass_fields__)
        self.assertIn("higher highs", trend.reason)
        # HTF series are causally rebuilt from M15; full MTF alignment is not
        # guaranteed when aggregated HTF lacks fractal swings.
        self.assertTrue(
            {"M30", "H1", "H4"} <= set(trend.by_timeframe),
            msg=f"expected rebuilt HTFs, got {set(trend.by_timeframe)}",
        )

    def test_trend_without_swings_is_not_bullish(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _monotonic_bars("EURUSD")},
            entry_timeframe="M15",
        )
        trend = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        self.assertNotEqual(trend.trend, MarketTrend.BULLISH)

    def test_range_expansion_uses_recent_body_size_against_historical_average(
        self,
    ) -> None:
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

    def test_multi_timeframe_disagreement_is_explained(self) -> None:
        # HTF OHLC is causally rebuilt from entry LTF when aggregatable, so
        # injected conflicting HTF series cannot survive materialize().
        # Disagreement scoring is verified directly on the agreement helper.
        from core.features.views.trend import (
            TimeframeTrendProjection,
            _multi_timeframe_agreement,
        )
        from core.features.config import default_feature_config

        config = default_feature_config()
        by_tf = {
            "M15": TimeframeTrendProjection(
                "M15", MarketTrend.BULLISH, "up", (), ()
            ),
            "M30": TimeframeTrendProjection(
                "M30", MarketTrend.BEARISH, "down", (), ()
            ),
            "H1": TimeframeTrendProjection(
                "H1", MarketTrend.BEARISH, "down", (), ()
            ),
            "H4": TimeframeTrendProjection(
                "H4", MarketTrend.BEARISH, "down", (), ()
            ),
        }
        mtf = _multi_timeframe_agreement(
            entry_timeframe="M15",
            entry_trend=MarketTrend.BULLISH,
            by_timeframe=by_tf,
            mapping=dict(config.multi_timeframe_mapping),
            config=config,
        )
        self.assertLess(mtf.score, config.trend_strength.aligned_structure_score)
        self.assertIn("do not align", mtf.reason)

    def test_materialize_rebuilds_htf_from_entry_so_injected_conflict_cannot_leak(
        self,
    ) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {
                "M15": _trend_bars("EURUSD", "up", count=200),
                "M30": _trend_bars("EURUSD", "down", count=200),
                "H1": _trend_bars("EURUSD", "down", count=200),
                "H4": _trend_bars("EURUSD", "down", count=200),
            },
            entry_timeframe="M15",
        )
        trend = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        self.assertEqual(trend.trend, MarketTrend.BULLISH)
        # Rebuilt HTFs from bullish M15 cannot retain the injected bearish series.
        for timeframe in ("M30", "H1", "H4"):
            if timeframe in context.bars_by_timeframe:
                # Swings/trend on rebuilt HTF should not be forced bearish by caller.
                self.assertNotEqual(
                    trend.by_timeframe[timeframe].trend,
                    MarketTrend.BEARISH,
                    msg=f"{timeframe} retained injected bearish structure",
                )

    def test_feature_context_has_no_confidence_field(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up")},
            entry_timeframe="M15",
        )
        self.assertFalse(hasattr(context, "confidence"))
        self.assertIn("price", {str(key) for key in context.packs})

    def test_feature_configuration_is_loaded_from_json(self) -> None:
        payload = {
            "swing_detection": {"left_bars": 1, "right_bars": 1, "minimum_swings": 2},
            "momentum": {
                "recent_window": 3,
                "historical_window": 10,
                "low_ratio": 0.7,
                "high_ratio": 1.3,
            },
            "ema": {"fast_period": 8, "slow_period": 21},
            "multi_timeframe_mapping": {"M15": ["H1"]},
            "market_phase": {
                "compression_momentum_score_max": 30,
                "strong_trend_score_min": 70,
                "pullback_recent_window": 3,
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "features.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_feature_config(config_path)

        self.assertEqual(config.indicators.ema_fast_period, 8)
        self.assertEqual(config.range_expansion.recent_window, 3)
        self.assertEqual(config.multi_timeframe_mapping["M15"], ("H1",))


if __name__ == "__main__":
    unittest.main()
