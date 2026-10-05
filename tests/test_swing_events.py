"""P1-5: swing event identity, timing, and causal confirmation tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from core.features import FeatureRepository, PACK_STRUCTURE
from core.features.config import SwingDetectionConfig
from core.features.generators.swings import (
    SwingEvent,
    SwingGenerator,
    SwingKind,
    make_swing_id,
)
from core.features.packs.base import StructurePack
from core.market import require_instrument
from core.market_state import MarketStateBuilder
from models.bar import Bar


def _bar(
    minute: int,
    *,
    high: float,
    low: float,
    close: float | None = None,
    open_: float | None = None,
    symbol: str = "EURUSD",
) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute),
        open=open_ if open_ is not None else mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=1.0,
    )


def _golden_bars() -> list[Bar]:
    highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
    lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
    return [
        _bar(i, high=float(h), low=float(l))
        for i, (h, l) in enumerate(zip(highs, lows, strict=True))
    ]


class SwingEventIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SwingDetectionConfig(left_bars=2, right_bars=2, minimum_swings=2)
        self.gen = SwingGenerator(self.config)
        self.instrument = require_instrument("EURUSD")
        self.bars = _golden_bars()
        self.features = self.gen.generate(
            {"M15": self.bars}, self.instrument, entry_timeframe="M15"
        )
        self.tf = self.features.by_timeframe["M15"]

    def test_golden_prices_unchanged(self) -> None:
        self.assertEqual(self.tf.swing_highs, (15.0, 14.0))
        self.assertEqual(self.tf.swing_lows, (7.0, 6.0))

    def test_high_and_low_kinds_explicit(self) -> None:
        kinds = {event.kind for event in self.tf.swings}
        self.assertEqual(kinds, {SwingKind.HIGH, SwingKind.LOW})
        self.assertTrue(all(e.kind == SwingKind.HIGH for e in self.tf.highs))
        self.assertTrue(all(e.kind == SwingKind.LOW for e in self.tf.lows))

    def test_swing_high_source_index(self) -> None:
        highs = self.tf.highs
        self.assertEqual(highs[0].index, 2)
        self.assertEqual(highs[0].price, 15.0)
        self.assertEqual(highs[1].index, 6)
        self.assertEqual(highs[1].price, 14.0)

    def test_swing_low_source_index(self) -> None:
        lows = self.tf.lows
        self.assertEqual(lows[0].index, 2)
        self.assertEqual(lows[0].price, 7.0)
        self.assertEqual(lows[1].index, 5)
        self.assertEqual(lows[1].price, 6.0)

    def test_source_timestamp_matches_bar(self) -> None:
        for event in self.tf.swings:
            self.assertEqual(event.timestamp, self.bars[event.index].timestamp)

    def test_confirmation_index_is_source_plus_right_bars(self) -> None:
        right = self.config.right_bars
        for event in self.tf.swings:
            self.assertEqual(event.confirmation_index, event.index + right)
            self.assertEqual(
                event.confirmation_time,
                self.bars[event.confirmation_index].timestamp,
            )

    def test_confirmation_time_later_than_candidate(self) -> None:
        for event in self.tf.swings:
            self.assertGreater(event.confirmation_time, event.timestamp)
            self.assertNotEqual(event.confirmation_time, event.timestamp)

    def test_last_right_bars_candidates_not_emitted(self) -> None:
        # Bars at indices 9 and 10 cannot confirm (need right=2).
        emitted_indices = {event.index for event in self.tf.swings}
        self.assertNotIn(9, emitted_indices)
        self.assertNotIn(10, emitted_indices)
        # High 16 at index 9 must not appear as a confirmed swing price.
        self.assertNotIn(16.0, self.tf.swing_highs)

    def test_chronological_detection_order(self) -> None:
        # Same loop order as legacy: high then low at same index.
        self.assertEqual(
            [(e.kind, e.index, e.price) for e in self.tf.swings],
            [
                (SwingKind.HIGH, 2, 15.0),
                (SwingKind.LOW, 2, 7.0),
                (SwingKind.LOW, 5, 6.0),
                (SwingKind.HIGH, 6, 14.0),
            ],
        )

    def test_equal_highs_still_rejected(self) -> None:
        highs = [10, 11, 15, 15, 11, 10, 9]
        lows = [9, 8, 7, 7, 8, 9, 8]
        bars = [
            _bar(i, high=float(h), low=float(l))
            for i, (h, l) in enumerate(zip(highs, lows, strict=True))
        ]
        features = self.gen.generate(
            {"M15": bars}, self.instrument, entry_timeframe="M15"
        )
        self.assertEqual(features.by_timeframe["M15"].swing_highs, ())
        self.assertEqual(features.by_timeframe["M15"].swings, ())

    def test_same_price_distinct_deterministic_ids(self) -> None:
        # Two equal-height peaks that are each strict local maxima vs neighbors.
        # Build: peaks at i=2 and i=7 both high=20 with L=R=2.
        highs = [10, 11, 20, 12, 11, 10, 11, 20, 12, 11, 10]
        lows = [9, 8, 7, 8, 9, 8, 7, 6, 7, 8, 9]
        bars = [
            _bar(i, high=float(h), low=float(l))
            for i, (h, l) in enumerate(zip(highs, lows, strict=True))
        ]
        features = self.gen.generate(
            {"M15": bars}, self.instrument, entry_timeframe="M15"
        )
        peak_highs = [
            e for e in features.by_timeframe["M15"].highs if e.price == 20.0
        ]
        self.assertEqual(len(peak_highs), 2)
        self.assertEqual(peak_highs[0].index, 2)
        self.assertEqual(peak_highs[1].index, 7)
        self.assertNotEqual(peak_highs[0].id, peak_highs[1].id)
        self.assertEqual(peak_highs[0].id, make_swing_id("M15", SwingKind.HIGH, 2))
        self.assertEqual(peak_highs[1].id, make_swing_id("M15", SwingKind.HIGH, 7))

    def test_ids_stable_across_repeated_materialization(self) -> None:
        first = self.gen.generate(
            {"M15": self.bars}, self.instrument, entry_timeframe="M15"
        )
        second = self.gen.generate(
            {"M15": list(self.bars)}, self.instrument, entry_timeframe="M15"
        )
        self.assertEqual(
            [e.id for e in first.by_timeframe["M15"].swings],
            [e.id for e in second.by_timeframe["M15"].swings],
        )
        self.assertEqual(
            first.by_timeframe["M15"].swings,
            second.by_timeframe["M15"].swings,
        )

    def test_serialization_round_trip(self) -> None:
        for event in self.tf.swings:
            restored = SwingEvent.from_dict(event.to_dict())
            self.assertEqual(restored, event)


class SwingCausalAsofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bars = _golden_bars()
        self.repo = FeatureRepository()

    def test_absent_before_confirmation(self) -> None:
        # First SH at i=2 confirms at i=4 → timestamp minute 4.
        asof = self.bars[3].timestamp  # before confirmation bar
        context = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        structure = context.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(structure, StructurePack)
        swings = structure.swings.by_timeframe["M15"]
        self.assertNotIn(15.0, swings.swing_highs)
        self.assertTrue(all(e.confirmation_time <= asof for e in swings.swings))

    def test_available_exactly_at_confirmation(self) -> None:
        asof = self.bars[4].timestamp  # confirmation of i=2 swings
        context = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        structure = context.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(structure, StructurePack)
        swings = structure.swings.by_timeframe["M15"]
        self.assertEqual(swings.swing_highs, (15.0,))
        self.assertEqual(swings.swing_lows, (7.0,))
        for event in swings.swings:
            self.assertEqual(event.confirmation_time, asof)
            self.assertLess(event.timestamp, event.confirmation_time)

    def test_available_after_confirmation(self) -> None:
        asof = self.bars[8].timestamp
        context = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        structure = context.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(structure, StructurePack)
        swings = structure.swings.by_timeframe["M15"]
        self.assertEqual(swings.swing_highs, (15.0, 14.0))
        self.assertEqual(swings.swing_lows, (7.0, 6.0))

    def test_future_mutation_does_not_alter_confirmed_swings(self) -> None:
        asof = self.bars[4].timestamp
        before = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        before_swings = before.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(before_swings, StructurePack)
        confirmed = before_swings.swings.by_timeframe["M15"].swings

        mutated = list(self.bars)
        for index in range(5, len(mutated)):
            bar = mutated[index]
            mutated[index] = Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=99.0,
                high=100.0,
                low=0.01,
                close=50.0,
                volume=999.0,
            )
        after = self.repo.materialize(
            "EURUSD",
            {"M15": mutated},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        after_swings = after.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(after_swings, StructurePack)
        self.assertEqual(
            after_swings.swings.by_timeframe["M15"].swings,
            confirmed,
        )
        # Extreme future highs must not create new confirmed swings at this asof.
        self.assertNotIn(100.0, after_swings.swings.by_timeframe["M15"].swing_highs)

    def test_generator_asof_filter_excludes_unconfirmed(self) -> None:
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        asof = self.bars[4].timestamp
        features = gen.generate(
            {"M15": self.bars},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
            asof=asof,
        )
        swings = features.by_timeframe["M15"]
        self.assertTrue(all(e.confirmation_time <= asof for e in swings.swings))
        self.assertEqual(swings.swing_highs, (15.0,))


class SwingMarketStateCompatibilityTests(unittest.TestCase):
    def test_market_state_includes_swing_events(self) -> None:
        bars = _golden_bars()
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": bars},
            entry_timeframe="M15",
            asof=bars[-1].timestamp,
        )
        state = MarketStateBuilder().build(context)
        assert state.structure.entry_timeframe is not None
        snapshot = state.structure.entry_timeframe
        self.assertEqual(snapshot.swing_highs, (15.0, 14.0))
        self.assertEqual(snapshot.swing_lows, (7.0, 6.0))
        self.assertGreaterEqual(len(snapshot.swings), 4)
        payload = snapshot.to_dict()
        self.assertIn("swings", payload)
        first = payload["swings"][0]
        for key in (
            "id",
            "kind",
            "price",
            "index",
            "timestamp",
            "confirmation_index",
            "confirmation_time",
            "timeframe",
        ):
            self.assertIn(key, first)
        restored = SwingEvent.from_dict(first)
        self.assertEqual(restored.kind, SwingKind.HIGH)
        self.assertEqual(restored.index, 2)


if __name__ == "__main__":
    unittest.main()
