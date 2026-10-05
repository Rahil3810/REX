"""P0-3: insufficient range-expansion data must be UNAVAILABLE, not NORMAL."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from core.features import (
    FeatureRepository,
    METHOD_PHASE_HEURISTIC_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PACK_VOLATILITY,
    PhaseView,
    VolatilityView,
)
from core.features.config import RangeExpansionConfig
from core.features.generators.range_expansion import RangeExpansionGenerator
from core.features.packs.base import VolatilityPack
from core.features.views.phase import _range_expansion_score
from core.market import require_instrument
from core.market_state import MarketStateBuilder, SectionStatus
from models.bar import Bar
from models.market_structure import RangeExpansionState


def _bars(count: int, *, body: float = 0.001) -> list[Bar]:
    start = datetime(2026, 6, 20, tzinfo=timezone.utc)
    bars: list[Bar] = []
    for index in range(count):
        close = 1.1000 + 0.0001 * index
        bars.append(
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=15 * index),
                open=close - body,
                high=close + body,
                low=close - body,
                close=close,
                volume=1.0,
            )
        )
    return bars


class RangeExpansionUnavailableTests(unittest.TestCase):
    def test_insufficient_bars_unavailable_not_normal(self) -> None:
        config = RangeExpansionConfig(
            recent_window=2, historical_window=20, low_ratio=0.7, high_ratio=1.3
        )
        result = RangeExpansionGenerator(config).generate(
            {"M15": _bars(5)},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
        )
        self.assertEqual(result.state, RangeExpansionState.UNAVAILABLE)
        self.assertIsNone(result.ratio)
        self.assertNotEqual(result.state, RangeExpansionState.NORMAL)

    def test_enough_data_within_thresholds_is_normal(self) -> None:
        config = RangeExpansionConfig(
            recent_window=2, historical_window=5, low_ratio=0.7, high_ratio=1.3
        )
        # Uniform bodies → ratio 1.0 → NORMAL
        result = RangeExpansionGenerator(config).generate(
            {"M15": _bars(5, body=0.001)},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
        )
        self.assertEqual(result.state, RangeExpansionState.NORMAL)
        self.assertIsNotNone(result.ratio)
        self.assertAlmostEqual(result.ratio or 0.0, 1.0, places=10)

    def test_zero_body_baseline_unavailable(self) -> None:
        config = RangeExpansionConfig(
            recent_window=2, historical_window=4, low_ratio=0.7, high_ratio=1.3
        )
        result = RangeExpansionGenerator(config).generate(
            {"M15": _bars(4, body=0.0)},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
        )
        self.assertEqual(result.state, RangeExpansionState.UNAVAILABLE)
        self.assertIsNone(result.ratio)

    def test_volatility_view_preserves_unavailable(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _bars(3)},
            entry_timeframe="M15",
            pack_ids=(PACK_VOLATILITY,),
        )
        projection = VolatilityView().project(
            context, METHOD_VOLATILITY_RANGE_EXPANSION_V1
        )
        self.assertEqual(projection.state, RangeExpansionState.UNAVAILABLE)
        self.assertIsNone(projection.ratio)

    def test_market_state_marks_volatility_section_unavailable(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _bars(3)},
            entry_timeframe="M15",
        )
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.volatility.status, SectionStatus.UNAVAILABLE)
        self.assertEqual(
            state.volatility.range_expansion_state,
            RangeExpansionState.UNAVAILABLE.value,
        )
        self.assertIsNone(state.volatility.range_expansion_ratio)

    def test_phase_does_not_treat_unavailable_as_compression(self) -> None:
        # Insufficient bars → UNAVAILABLE range expansion; unknown/ranging trend
        # path must not invent COMPRESSION via a LOW-like score.
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _bars(3)},
            entry_timeframe="M15",
        )
        phase = PhaseView().project(context, METHOD_PHASE_HEURISTIC_V1)
        self.assertNotEqual(phase.phase.value, "compression")
        pack = context.require_pack(PACK_VOLATILITY, VolatilityPack)
        assert isinstance(pack, VolatilityPack)
        self.assertEqual(pack.range_expansion.state, RangeExpansionState.UNAVAILABLE)

    def test_unavailable_has_no_regime_score(self) -> None:
        from core.features.config import default_feature_config

        with self.assertRaises(ValueError):
            _range_expansion_score(
                RangeExpansionState.UNAVAILABLE, default_feature_config()
            )


if __name__ == "__main__":
    unittest.main()
