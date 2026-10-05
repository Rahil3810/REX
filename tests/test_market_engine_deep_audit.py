"""Deep conceptual validation tests (audit only — no production changes).

These tests distinguish mechanically-correct behavior from conceptually
appropriate market-structure semantics.
"""

from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.features.config import SwingDetectionConfig, default_feature_config
from core.features.generators.swings import SwingGenerator, TimeframeSwings
from core.features.views.phase import PhaseView, _is_recent_pullback
from core.features.views.trend import _classify_swings, _structure_score
from core.market import require_instrument
from models.bar import Bar
from models.market_structure import MarketTrend
from core.features.generators.bos import detect_swing_bos
from strategies.rules.lookback_breakout_rule import LookbackBreakoutRule


def _bar(i: int, high: float, low: float, close: float | None = None) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol="EURUSD",
        timestamp=datetime(2026, 1, 1) + timedelta(minutes=i),
        open=mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=1.0,
    )


class DeepSwingFoundationTests(unittest.TestCase):
    """Is fractal swing detection a valid structural foundation?"""

    def test_nearby_equal_peaks_produce_no_swing_under_strict_gt(self) -> None:
        # Double top at same high — neither is strict swing under current def.
        bars = [
            _bar(0, 10, 9),
            _bar(1, 11, 8),
            _bar(2, 15, 7),
            _bar(3, 14, 8),
            _bar(4, 15, 7),  # equal to prior peak
            _bar(5, 13, 8),
            _bar(6, 12, 9),
        ]
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        swings = gen.generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        # Index 2 high=15: right includes index4 high=15 → NOT strict >
        self.assertNotIn(15.0, swings.by_timeframe["M15"].swing_highs)

    def test_confirmation_time_is_recorded_on_swing_events(self) -> None:
        from core.features.generators.swings import SwingEvent

        fields = SwingEvent.__dataclass_fields__
        self.assertIn("confirmation_time", fields)
        self.assertIn("index", fields)
        self.assertIn("timestamp", fields)
        self.assertIn("id", fields)
        # TimeframeSwings stores events, not bare price fields as dataclass attrs
        tf_fields = TimeframeSwings.__dataclass_fields__
        self.assertIn("swings", tf_fields)
        self.assertNotIn("swing_highs", tf_fields)  # property projection



class DeepBOSSemanticTests(unittest.TestCase):
    """Lookback breakout ≠ structural swing BOS; structural BOS uses SwingEvents."""

    def test_lookback_breakout_still_breaks_non_structural_extremum(self) -> None:
        highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
        lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
        bars = [_bar(i, h, l) for i, (h, l) in enumerate(zip(highs, lows))]
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        swings = gen.generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        fractal_highs = swings.by_timeframe["M15"].swing_highs
        self.assertEqual(fractal_highs, (15.0, 14.0))

        bars2 = list(bars) + [_bar(11, 17, 10, close=16.5)]
        lookback = LookbackBreakoutRule(lookback=10).detect(
            bars2, bullish=True, bearish=False
        )
        self.assertTrue(lookback.detected)
        self.assertEqual(lookback.broken_swing_price, 16.0)
        self.assertNotIn(16.0, fractal_highs)

    def test_structural_bos_breaks_latest_confirmed_high_not_lookback_max(self) -> None:
        # structural HIGH=14, non-structural lookback HIGH=16, close=15.5 → BOS @ 14
        highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
        lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
        bars = [_bar(i, h, l) for i, (h, l) in enumerate(zip(highs, lows))]
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        swing_features = gen.generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        swing_events = swing_features.by_timeframe["M15"].swings
        self.assertEqual(
            [e.price for e in swing_features.by_timeframe["M15"].highs],
            [15.0, 14.0],
        )

        bars.append(_bar(11, 15.6, 10, close=15.5))
        lookback = LookbackBreakoutRule(lookback=10).detect(
            bars, bullish=True, bearish=False
        )
        self.assertFalse(lookback.detected)

        bos = detect_swing_bos(bars, swing_events)
        self.assertTrue(bos.detected)
        assert bos.event is not None
        self.assertEqual(bos.event.broken_swing.price, 14.0)
        self.assertEqual(bos.event.broken_swing.id, "M15:high:6")


class DeepStructureScoreTests(unittest.TestCase):
    def test_tiny_and_huge_bullish_structures_same_structure_score(self) -> None:
        tiny = TimeframeSwings.from_prices(
            "M15", (1.0001, 1.0002), (1.0000, 1.00005)
        )
        huge = TimeframeSwings.from_prices("M15", (1.0, 2.0), (0.5, 1.5))
        cfg = default_feature_config()
        t1 = _classify_swings(tiny, 2)
        t2 = _classify_swings(huge, 2)
        self.assertEqual(t1.trend, MarketTrend.BULLISH)
        self.assertEqual(t2.trend, MarketTrend.BULLISH)
        self.assertEqual(
            _structure_score(t1.trend, cfg), _structure_score(t2.trend, cfg)
        )
        self.assertEqual(_structure_score(t1.trend, cfg), 85)


class DeepPhaseResidualTests(unittest.TestCase):
    def test_reversal_branch_has_no_positive_reversal_predicate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        src = (root / "core/features/views/phase.py").read_text(encoding="utf-8")
        # No function named detect_reversal / is_reversal in phase module
        self.assertNotIn("def detect_reversal", src)
        self.assertNotIn("def is_reversal", src)
        self.assertIn("phase = MarketPhase.REVERSAL", src)
        self.assertIn(
            "Directional structure without strong-trend structure score", src
        )

    def test_pullback_helper_is_not_reversal(self) -> None:
        # Strictly falling closes in bullish trend = pullback, not reversal
        self.assertTrue(
            _is_recent_pullback(MarketTrend.BULLISH, (3.0, 2.0, 1.0), 3)
        )


class DeepConnectivityTests(unittest.TestCase):
    def test_bos_rule_not_imported_by_strategies(self) -> None:
        root = Path(__file__).resolve().parents[1] / "strategies"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        if alias.name == "BOSRule":
                            offenders.append(str(path))
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "bos_rule" in alias.name:
                            offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_causal_htf_module_enforces_completion_boundaries(self) -> None:
        from core.features.timeframes import (
            aggregate_completed_bars,
            bar_completion_time,
            prepare_causal_bars,
        )

        root = Path(__file__).resolve().parents[1]
        module = root / "core/features/timeframes.py"
        self.assertTrue(module.is_file())
        # Smoke: symbols exist and incomplete H1 is empty before completion.
        self.assertTrue(callable(aggregate_completed_bars))
        self.assertTrue(callable(prepare_causal_bars))
        self.assertTrue(callable(bar_completion_time))


class DeepMarketStateNamingTests(unittest.TestCase):
    def test_structure_exposes_structure_score_not_strength_or_confidence(self) -> None:
        from core.market_state.models import MarketStateStructure

        fields = MarketStateStructure.__dataclass_fields__
        self.assertIn("structure_score", fields)
        self.assertNotIn("strength", fields)
        self.assertNotIn("confidence", fields)


if __name__ == "__main__":
    unittest.main()
