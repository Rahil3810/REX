"""Tests for MarketStructureAnalyzer V1."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.market_structure_analyzer import MarketStructureAnalyzer
from core.market_structure_config import load_market_structure_config
from models.bar import Bar
from models.market_structure import MarketPhase, MarketTrend, MomentumState


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


class MarketStructureAnalyzerTests(unittest.TestCase):
    def test_detects_bullish_structure_from_higher_highs_and_lows(self) -> None:
        analyzer = MarketStructureAnalyzer()
        result = analyzer.analyze(
            symbol="EURUSD",
            entry_timeframe="M15",
            bars_by_timeframe={
                "M15": _trend_bars("EURUSD", "up"),
                "M30": _trend_bars("EURUSD", "up"),
                "H1": _trend_bars("EURUSD", "up"),
                "H4": _trend_bars("EURUSD", "up"),
            },
        )

        self.assertEqual(result.trend, MarketTrend.BULLISH)
        self.assertEqual(result.market_phase, MarketPhase.TREND)
        self.assertGreater(result.trend_strength, 0)
        self.assertGreater(result.confidence, 0)
        self.assertIn("higher highs", result.trend_structure_score.reason)
        self.assertIn("All configured higher timeframes agree", result.multi_timeframe_score.reason)

    def test_ema_alignment_does_not_determine_trend_without_swings(self) -> None:
        analyzer = MarketStructureAnalyzer()
        result = analyzer.analyze(
            symbol="EURUSD",
            entry_timeframe="M15",
            bars_by_timeframe={"M15": _monotonic_bars("EURUSD")},
        )

        self.assertNotEqual(result.trend, MarketTrend.BULLISH)
        self.assertIn("swing structure is not directional", result.ema_alignment_score.reason)

    def test_momentum_uses_recent_body_size_against_historical_average(self) -> None:
        analyzer = MarketStructureAnalyzer()
        result = analyzer.analyze(
            symbol="EURUSD",
            entry_timeframe="M15",
            bars_by_timeframe={"M15": _trend_bars("EURUSD", "up", large_recent_body=True)},
        )

        self.assertEqual(result.momentum, MomentumState.HIGH)
        self.assertIn("Recent average candle body", result.momentum_score.reason)

    def test_multi_timeframe_disagreement_is_scored_and_explained(self) -> None:
        analyzer = MarketStructureAnalyzer()
        result = analyzer.analyze(
            symbol="EURUSD",
            entry_timeframe="M15",
            bars_by_timeframe={
                "M15": _trend_bars("EURUSD", "up"),
                "M30": _trend_bars("EURUSD", "down"),
                "H1": _trend_bars("EURUSD", "down"),
                "H4": _trend_bars("EURUSD", "down"),
            },
        )

        self.assertEqual(result.trend, MarketTrend.BULLISH)
        self.assertLess(
            result.multi_timeframe_score.score,
            result.trend_structure_score.score,
        )
        self.assertIn("do not align", result.multi_timeframe_score.reason)

    def test_market_structure_to_dict_contains_explainable_component_scores(self) -> None:
        analyzer = MarketStructureAnalyzer()
        result = analyzer.analyze(
            symbol="EURUSD",
            entry_timeframe="M15",
            bars_by_timeframe={"M15": _trend_bars("EURUSD", "up")},
        )
        payload = result.to_dict()

        self.assertEqual(payload["trend"], "bullish")
        self.assertIn("component_scores", payload)
        component_scores = payload["component_scores"]
        assert isinstance(component_scores, dict)
        self.assertIn("reason", component_scores["price_action"])
        self.assertNotIn("signal", payload)

    def test_market_structure_configuration_is_loaded_from_json(self) -> None:
        payload = {
            "component_weights": {
                "price_action": 1.0,
                "multi_timeframe": 1.0,
                "trend_structure": 1.0,
                "momentum": 1.0,
                "ema_alignment": 1.0,
            },
            "ema": {"fast_period": 8, "slow_period": 21},
            "swing_detection": {"left_bars": 1, "right_bars": 1, "minimum_swings": 2},
            "momentum": {
                "recent_window": 3,
                "historical_window": 10,
                "low_ratio": 0.7,
                "high_ratio": 1.3,
            },
            "trend_scoring": {
                "aligned_structure_score": 80,
                "partial_structure_score": 50,
                "ranging_score": 30,
                "unknown_score": 0,
            },
            "component_score_values": {
                "aligned": 80,
                "partial": 50,
                "neutral": 30,
                "unknown": 0,
                "momentum_low": 30,
                "momentum_normal": 60,
                "momentum_high": 80,
            },
            "confidence_thresholds": {"high": 75, "medium": 50, "low": 25},
            "multi_timeframe_mapping": {"M15": ["H1"]},
            "market_phase": {
                "compression_momentum_score_max": 30,
                "strong_trend_score_min": 70,
                "pullback_recent_window": 3,
            },
            "future_scoring_parameters": {},
        }

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "market_structure.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_market_structure_config(config_path)

        self.assertEqual(config.ema.fast_period, 8)
        self.assertEqual(config.momentum.recent_window, 3)
        self.assertEqual(config.multi_timeframe_mapping["M15"], ("H1",))


if __name__ == "__main__":
    unittest.main()
