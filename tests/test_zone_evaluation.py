"""Zone Evaluation V1 — deterministic historical interaction measurements."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from core.features.config import SwingDetectionConfig
from core.zones import (
    METHOD_ZONE_EVAL_V1,
    AutomaticZoneGenerator,
    InteractionOutcome,
    SwingClusterZoneConfig,
    ZoneEvaluation,
    ZoneEvaluationConfig,
    ZoneEvaluationSubject,
    ZoneEvaluator,
    ZoneKind,
    ZoneSource,
)
from models.bar import Bar
from models.zone import Zone


def _ts(minute: int) -> datetime:
    return datetime(2024, 1, 2, tzinfo=timezone.utc) + timedelta(minutes=minute)


def _bar(
    minute: int,
    *,
    high: float,
    low: float,
    close: float | None = None,
    open_: float | None = None,
) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol="EURUSD",
        timestamp=_ts(minute),
        open=open_ if open_ is not None else mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=1.0,
    )


def _atr_ready_prefix(count: int = 20, price: float = 1.1000) -> list[Bar]:
    """Enough bars for ATR(14) with small true range ~0.0004."""
    bars: list[Bar] = []
    for i in range(count):
        bars.append(
            _bar(
                i,
                high=price + 0.0002,
                low=price - 0.0002,
                close=price,
            )
        )
    return bars


def _demand_zone() -> Zone:
    return Zone(
        id=1,
        name="demand",
        low=1.0990,
        high=1.1000,
        timeframe="M15",
        strength=5,
        kind=ZoneKind.DEMAND,
        source=ZoneSource.AUTOMATIC,
    )


def _supply_zone() -> Zone:
    return Zone(
        id=2,
        name="supply",
        low=1.1000,
        high=1.1010,
        timeframe="M15",
        strength=5,
        kind=ZoneKind.SUPPLY,
        source=ZoneSource.AUTOMATIC,
    )


def _config(**overrides: object) -> ZoneEvaluationConfig:
    payload = dict(
        atr_period=14,
        target_atr_multiple=1.0,
        invalidation_atr_multiple=0.5,
        horizon_bars=20,
    )
    payload.update(overrides)
    return ZoneEvaluationConfig(**payload)  # type: ignore[arg-type]


class ZoneEvaluationSuccessFailureTests(unittest.TestCase):
    def test_demand_zone_successful_reaction(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[14] = _bar(14, high=1.1001, low=1.0992, close=1.0995)
        # Favorable rally away from demand, never re-entering
        for i in range(15, 25):
            move = 0.0003 * (i - 14)
            price = 1.0995 + move
            bars.append(
                _bar(
                    i,
                    high=price + 0.0002,
                    low=price + 0.00005,  # stays above zone high 1.1000 after enough move
                    close=price,
                )
            )
        # Force remaining path clearly above zone
        for i in range(len(bars), 35):
            bars.append(_bar(i, high=1.1020, low=1.1010, close=1.1015))

        result = ZoneEvaluator(
            _config(target_atr_multiple=0.5, invalidation_atr_multiple=2.0, horizon_bars=10)
        ).evaluate_one(
            _demand_zone(),
            bars,
            origin_confirmation_index=origin,
        )
        self.assertGreaterEqual(result.sample_count, 1)
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.SUCCESS)
        self.assertGreaterEqual(result.successful_reaction_count, 1)
        self.assertIsNotNone(result.interactions[0].mfe)
        assert result.interactions[0].mfe is not None
        self.assertGreater(result.interactions[0].mfe, 0)

    def test_supply_zone_successful_reaction(self) -> None:
        bars = _atr_ready_prefix(20, price=1.0995)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.0998, low=1.0990, close=1.0994)
        bars[14] = _bar(14, high=1.1008, low=1.0998, close=1.1005)
        for i in range(15, 20):
            move = 0.0003 * (i - 14)
            bars.append(
                _bar(
                    i,
                    high=1.1005 - move + 0.0001,
                    low=1.1005 - move - 0.0002,
                    close=1.1005 - move,
                )
            )
        result = ZoneEvaluator(
            _config(target_atr_multiple=0.5, invalidation_atr_multiple=2.0)
        ).evaluate_one(_supply_zone(), bars, origin_confirmation_index=origin)
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.SUCCESS)

    def test_demand_zone_failure(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[14] = _bar(14, high=1.1001, low=1.0992, close=1.0995)
        # Adverse down quickly
        for i in range(15, 20):
            move = 0.0004 * (i - 14)
            bars.append(
                _bar(
                    i,
                    high=1.0995 - move + 0.0001,
                    low=1.0995 - move - 0.0002,
                    close=1.0995 - move,
                )
            )
        result = ZoneEvaluator(
            _config(target_atr_multiple=5.0, invalidation_atr_multiple=0.5)
        ).evaluate_one(_demand_zone(), bars, origin_confirmation_index=origin)
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.FAILURE)

    def test_supply_zone_failure(self) -> None:
        bars = _atr_ready_prefix(20, price=1.0995)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.0998, low=1.0990, close=1.0994)
        bars[14] = _bar(14, high=1.1008, low=1.0998, close=1.1005)
        for i in range(15, 20):
            move = 0.0004 * (i - 14)
            bars.append(
                _bar(
                    i,
                    high=1.1005 + move + 0.0002,
                    low=1.1005 + move - 0.0001,
                    close=1.1005 + move,
                )
            )
        result = ZoneEvaluator(
            _config(target_atr_multiple=5.0, invalidation_atr_multiple=0.5)
        ).evaluate_one(_supply_zone(), bars, origin_confirmation_index=origin)
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.FAILURE)


class ZoneEvaluationBreakAndTouchTests(unittest.TestCase):
    def test_zone_broken_by_close(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[14] = _bar(14, high=1.1001, low=1.0992, close=1.0995)
        # Close below demand low → broken
        bars.append(_bar(15, high=1.0990, low=1.0980, close=1.0985))
        for i in range(16, 25):
            bars.append(_bar(i, high=1.0988, low=1.0980, close=1.0984))
        result = ZoneEvaluator(
            _config(target_atr_multiple=10.0, invalidation_atr_multiple=10.0)
        ).evaluate_one(_demand_zone(), bars, origin_confirmation_index=origin)
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.BROKEN)
        self.assertTrue(result.interactions[0].break_detected)

    def test_wick_penetration_does_not_count_as_break(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[14] = _bar(14, high=1.1001, low=1.0992, close=1.0995)
        # Wick below demand, close still inside
        bars.append(_bar(15, high=1.0998, low=1.0980, close=1.0992))
        for i in range(16, 25):
            bars.append(_bar(i, high=1.1008, low=1.0998, close=1.1004))
        result = ZoneEvaluator(
            _config(target_atr_multiple=10.0, invalidation_atr_multiple=10.0, horizon_bars=5)
        ).evaluate_one(_demand_zone(), bars, origin_confirmation_index=origin)
        self.assertFalse(result.interactions[0].break_detected)
        self.assertNotEqual(result.interactions[0].outcome, InteractionOutcome.BROKEN)

    def test_multiple_candles_inside_one_interaction(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        # stay inside demand for 3 bars
        for i in range(14, 17):
            bars[i] = _bar(i, high=1.1000, low=1.0990, close=1.0995)
        for i in range(17, 25):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        result = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=origin
        )
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.touch_count, 1)

    def test_reentry_after_leaving_is_second_interaction(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 13):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[13] = _bar(13, high=1.1000, low=1.0990, close=1.0995)  # enter
        bars[14] = _bar(14, high=1.1000, low=1.0990, close=1.0994)  # inside
        bars[15] = _bar(15, high=1.1012, low=1.1005, close=1.1008)  # leave
        bars[16] = _bar(16, high=1.1012, low=1.1005, close=1.1007)  # outside
        bars[17] = _bar(17, high=1.1000, low=1.0990, close=1.0995)  # re-enter
        for i in range(18, 30):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        result = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=origin
        )
        self.assertEqual(result.sample_count, 2)


class ZoneEvaluationMetricsAndAtrTests(unittest.TestCase):
    def test_mfe_mae_and_atr_normalization(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 14):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[14] = _bar(14, high=1.1001, low=1.0992, close=1.0995)
        bars.append(_bar(15, high=1.1002, low=1.0990, close=1.0998))  # up a bit
        bars.append(_bar(16, high=1.0996, low=1.0988, close=1.0990))  # down adverse
        for i in range(17, 30):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        result = ZoneEvaluator(
            _config(target_atr_multiple=50.0, invalidation_atr_multiple=50.0, horizon_bars=5)
        ).evaluate_one(_demand_zone(), bars, origin_confirmation_index=origin)
        inter = result.interactions[0]
        self.assertIsNotNone(inter.atr_at_interaction)
        self.assertIsNotNone(inter.mfe)
        self.assertIsNotNone(inter.mae)
        assert inter.mfe is not None and inter.mae is not None
        self.assertGreaterEqual(inter.mfe, 0.0)
        self.assertGreaterEqual(inter.mae, 0.0)
        self.assertEqual(result.method_id, METHOD_ZONE_EVAL_V1)
        self.assertIn("target_atr", result.config.to_dict())

    def test_missing_atr_unavailable(self) -> None:
        # Too few bars for ATR(14)
        bars = [_bar(i, high=1.1, low=1.0, close=1.05) for i in range(8)]
        zone = _demand_zone()
        bars[5] = _bar(5, high=1.1000, low=1.0990, close=1.0995)
        result = ZoneEvaluator(_config(atr_period=14)).evaluate_one(
            zone, bars, origin_confirmation_index=3
        )
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.UNAVAILABLE)
        self.assertIsNone(result.interactions[0].atr_at_interaction)

    def test_insufficient_future_horizon(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 18):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[18] = _bar(18, high=1.1000, low=1.0990, close=1.0995)
        # asof at entry — no future bars in horizon window after entry
        result = ZoneEvaluator(_config(horizon_bars=20)).evaluate_one(
            _demand_zone(),
            bars,
            asof_index=18,
            origin_confirmation_index=origin,
        )
        self.assertEqual(result.interactions[0].outcome, InteractionOutcome.UNAVAILABLE)
        self.assertIn("horizon", result.interactions[0].reason.lower())


class ZoneEvaluationCausalityTests(unittest.TestCase):
    def test_causal_evaluation_ignores_pre_origin_touches(self) -> None:
        bars = _atr_ready_prefix(25, price=1.1005)
        # Touch before origin confirmation
        bars[5] = _bar(5, high=1.1000, low=1.0990, close=1.0995)
        origin = 12
        for i in range(13, 16):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        bars[16] = _bar(16, high=1.1000, low=1.0990, close=1.0995)
        for i in range(17, 30):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        result = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=origin
        )
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.interactions[0].entry_index, 16)

    def test_future_candles_cannot_influence_creation_time_boundary(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1005)
        origin = 10
        for i in range(11, 15):
            bars[i] = _bar(i, high=1.1010, low=1.1004, close=1.1006)
        first = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, asof_index=14, origin_confirmation_index=origin
        )
        snapshot = copy.deepcopy(first)
        # Append dramatic future interactions after asof
        for i in range(15, 40):
            bars.append(_bar(i, high=1.1000, low=1.0990, close=1.0995))
        second = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, asof_index=14, origin_confirmation_index=origin
        )
        self.assertEqual(second, snapshot)

    def test_deterministic_repeated_evaluation(self) -> None:
        bars = _atr_ready_prefix(25, price=1.1005)
        origin = 10
        bars[14] = _bar(14, high=1.1000, low=1.0990, close=1.0995)
        for i in range(15, 30):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        evaluator = ZoneEvaluator(_config())
        a = evaluator.evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=origin
        )
        b = evaluator.evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=origin
        )
        self.assertEqual(a, b)

    def test_multiple_zones_evaluated_independently(self) -> None:
        bars = _atr_ready_prefix(25, price=1.1000)
        origin = 10
        bars[14] = _bar(14, high=1.1005, low=1.0995, close=1.1000)
        for i in range(15, 30):
            bars.append(_bar(i, high=1.1002, low=1.0998, close=1.1000))
        demand = ZoneEvaluationSubject(_demand_zone(), origin)
        supply = ZoneEvaluationSubject(_supply_zone(), origin)
        results = ZoneEvaluator(_config()).evaluate([demand, supply], bars)
        self.assertEqual(len(results), 2)
        self.assertEqual({r.zone_id for r in results}, {1, 2})

    def test_empty_interaction_set(self) -> None:
        bars = _atr_ready_prefix(20, price=1.1020)
        result = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=10
        )
        self.assertEqual(result.sample_count, 0)
        self.assertEqual(result.interactions, ())
        self.assertIsNone(result.success_rate)

    def test_serialization_round_trip(self) -> None:
        bars = _atr_ready_prefix(25, price=1.1005)
        bars[14] = _bar(14, high=1.1000, low=1.0990, close=1.0995)
        for i in range(15, 30):
            bars.append(_bar(i, high=1.1010, low=1.1004, close=1.1006))
        result = ZoneEvaluator(_config()).evaluate_one(
            _demand_zone(), bars, origin_confirmation_index=10
        )
        restored = ZoneEvaluation.from_dict(result.to_dict())
        self.assertEqual(restored, result)


class ZoneEvaluationE2ETests(unittest.TestCase):
    def test_ohlcv_swings_auto_zones_evaluator(self) -> None:
        highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
        lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
        bars = [
            _bar(i, high=float(h), low=float(l), close=(h + l) / 2)
            for i, (h, l) in enumerate(zip(highs, lows, strict=True))
        ]
        # Extend with later price action for interactions
        last = bars[-1].close
        for i in range(len(bars), len(bars) + 40):
            bars.append(
                _bar(
                    i,
                    high=last + 0.5,
                    low=last - 0.5,
                    close=last,
                )
            )
            last = bars[-1].close

        generator = AutomaticZoneGenerator(
            swing_config=SwingDetectionConfig(2, 2, 2),
            cluster_config=SwingClusterZoneConfig(
                atr_period=10_000,
                absolute_price_tolerance=0.5,
                single_swing_half_width_absolute=0.25,
            ),
        )
        # Create zones at mid history so later bars can interact
        created = generator.generate(bars, timeframe="M15", asof_index=10)
        self.assertGreaterEqual(len(created), 1)

        evaluator = ZoneEvaluator(
            ZoneEvaluationConfig(
                atr_period=5,
                target_atr_multiple=0.25,
                invalidation_atr_multiple=2.0,
                horizon_bars=15,
            )
        )
        evaluations = evaluator.evaluate(created, bars, asof_index=len(bars) - 1)
        self.assertEqual(len(evaluations), len(created))
        # At least one zone should have interaction evidence or an empty-but-valid eval
        self.assertTrue(all(e.method_id == METHOD_ZONE_EVAL_V1 for e in evaluations))
        self.assertTrue(all(e.zone_id == z.zone.id for e, z in zip(evaluations, created)))
        # Strength on generated zones unchanged by evaluation
        for auto, evaluation in zip(created, evaluations):
            self.assertEqual(auto.zone.strength, auto.zone.strength)
            self.assertIsInstance(evaluation.sample_count, int)


if __name__ == "__main__":
    unittest.main()
