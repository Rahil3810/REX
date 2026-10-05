"""P0-4: structure score naming must not look like confidence."""

from __future__ import annotations

import unittest

from core.features import (
    FeatureRepository,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    TrendView,
)
from core.features.config import default_feature_config
from core.features.generators.swings import TimeframeSwings
from core.features.views.trend import TrendProjection, _classify_swings, _structure_score
from core.market_state import MarketStateBuilder
from core.market_state.models import MarketStateStructure
from models.market_structure import MarketTrend


class StructureScoreNamingTests(unittest.TestCase):
    def test_trend_projection_field_is_structure_score(self) -> None:
        fields = TrendProjection.__dataclass_fields__
        self.assertIn("structure_score", fields)
        self.assertNotIn("strength", fields)
        self.assertNotIn("confidence", fields)

    def test_market_state_structure_json_uses_structure_score(self) -> None:
        fields = MarketStateStructure.__dataclass_fields__
        self.assertIn("structure_score", fields)
        self.assertNotIn("strength", fields)
        self.assertNotIn("confidence", fields)

    def test_aligned_structure_still_scores_85(self) -> None:
        config = default_feature_config()
        self.assertEqual(
            _structure_score(MarketTrend.BULLISH, config),
            config.trend_strength.aligned_structure_score,
        )
        self.assertEqual(_structure_score(MarketTrend.BULLISH, config), 85)
        self.assertEqual(_structure_score(MarketTrend.RANGING, config), 35)
        self.assertEqual(_structure_score(MarketTrend.UNKNOWN, config), 0)

    def test_score_invariant_to_price_magnitude(self) -> None:
        tiny = _classify_swings(
            TimeframeSwings.from_prices(
                "M15", (1.0001, 1.0002), (1.0000, 1.00005)
            ),
            2,
        )
        huge = _classify_swings(
            TimeframeSwings.from_prices("M15", (1.0, 2.0), (0.5, 1.5)), 2
        )
        config = default_feature_config()
        self.assertEqual(tiny.trend, MarketTrend.BULLISH)
        self.assertEqual(huge.trend, MarketTrend.BULLISH)
        self.assertEqual(
            _structure_score(tiny.trend, config),
            _structure_score(huge.trend, config),
        )

    def test_materialized_market_state_omits_strength_key(self) -> None:
        from datetime import datetime, timedelta, timezone

        from models.bar import Bar

        start = datetime(2026, 6, 20, tzinfo=timezone.utc)
        bars = []
        for index in range(70):
            close = 1.1 + 0.001 * index
            high = close + (0.003 if index % 6 == 2 else 0.0006)
            low = close - (0.003 if index % 6 == 5 else 0.0006)
            bars.append(
                Bar(
                    symbol="EURUSD",
                    timestamp=start + timedelta(minutes=15 * index),
                    open=close - 0.0004,
                    high=high,
                    low=low,
                    close=close,
                )
            )
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": bars},
            entry_timeframe="M15",
        )
        trend = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        state = MarketStateBuilder().build(context)
        self.assertEqual(trend.structure_score, state.structure.structure_score)
        structure_payload = state.to_dict()["structure"]
        self.assertIn("structure_score", structure_payload)
        self.assertNotIn("strength", structure_payload)
        self.assertNotIn("confidence", structure_payload)


if __name__ == "__main__":
    unittest.main()
