"""P0-1 causal HTF construction regression tests.

Independently assert the temporal invariant:
mutating future LTF bars must not change HTF features evaluated at earlier T.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.features import (
    FeatureRepository,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    PACK_INDICATORS,
    PACK_STRUCTURE,
    TrendView,
)
from core.features.config import default_feature_config
from core.features.packs.base import IndicatorPack, StructurePack
from core.features.timeframes import (
    aggregate_completed_bars,
    bar_completion_time,
    ensure_utc,
    filter_bars_available_at,
    floor_to_timeframe,
    interval_bounds,
    prepare_causal_bars,
    timeframe_minutes,
)
from models.bar import Bar


def _m1_bar(
    minute: datetime,
    *,
    open_: float = 1.0,
    high: float = 1.0,
    low: float = 1.0,
    close: float = 1.0,
    volume: float = 1.0,
    symbol: str = "EURUSD",
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ensure_utc(minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _m1_hour(
    hour_start: datetime,
    *,
    close_base: float = 1.1000,
    symbol: str = "EURUSD",
) -> list[Bar]:
    """Sixty contiguous M1 bars for ``[hour_start, hour_start+1h)``."""
    start = ensure_utc(hour_start)
    bars: list[Bar] = []
    for index in range(60):
        close = close_base + 0.0001 * index
        bars.append(
            _m1_bar(
                start + timedelta(minutes=index),
                open_=close - 0.00005,
                high=close + 0.0002,
                low=close - 0.0002,
                close=close,
                symbol=symbol,
            )
        )
    return bars


class TimeframeContractUnitTests(unittest.TestCase):
    def test_h1_interval_bounds(self) -> None:
        start, end, completion = interval_bounds(
            datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc), "H1"
        )
        self.assertEqual(start, datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc))
        self.assertEqual(completion, end)

    def test_ensure_utc_naive_is_utc(self) -> None:
        naive = datetime(2026, 8, 29, 10, 37)
        self.assertEqual(ensure_utc(naive).tzinfo, timezone.utc)
        self.assertEqual(ensure_utc(naive).hour, 10)


class CausalAggregationTests(unittest.TestCase):
    def test_incomplete_h1_excluded_at_1037(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(hour)
        asof = datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc)
        h1 = aggregate_completed_bars(
            m1,
            source_timeframe="M1",
            target_timeframe="H1",
            asof=asof,
            symbol="EURUSD",
        )
        self.assertEqual(h1, ())

    def test_h1_unavailable_at_1059_59(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(hour)
        asof = datetime(2026, 8, 29, 10, 59, 59, tzinfo=timezone.utc)
        h1 = aggregate_completed_bars(
            m1,
            source_timeframe="M1",
            target_timeframe="H1",
            asof=asof,
            symbol="EURUSD",
        )
        self.assertEqual(h1, ())

    def test_h1_available_at_exactly_1100(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(hour, close_base=1.2)
        asof = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
        h1 = aggregate_completed_bars(
            m1,
            source_timeframe="M1",
            target_timeframe="H1",
            asof=asof,
            symbol="EURUSD",
        )
        self.assertEqual(len(h1), 1)
        self.assertEqual(h1[0].timestamp, hour)
        self.assertEqual(h1[0].open, m1[0].open)
        self.assertEqual(h1[0].close, m1[-1].close)
        self.assertEqual(h1[0].high, max(bar.high for bar in m1))
        self.assertEqual(h1[0].low, min(bar.low for bar in m1))
        self.assertEqual(bar_completion_time(h1[0], "H1"), asof)

    def test_only_completed_htf_bars_available_at_t(self) -> None:
        day = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        m1: list[Bar] = []
        for hour_offset in range(4):
            m1.extend(
                _m1_hour(day + timedelta(hours=hour_offset), close_base=1.0 + hour_offset)
            )
        asof = datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc)
        h1 = aggregate_completed_bars(
            m1,
            source_timeframe="M1",
            target_timeframe="H1",
            asof=asof,
            symbol="EURUSD",
        )
        # Completed: 08:00 and 09:00. Incomplete: 10:00.
        self.assertEqual(
            [bar.timestamp for bar in h1],
            [
                datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc),
            ],
        )

    def test_missing_source_bar_does_not_invent_htf(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(hour)
        del m1[30]  # gap
        asof = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
        h1 = aggregate_completed_bars(
            m1,
            source_timeframe="M1",
            target_timeframe="H1",
            asof=asof,
            symbol="EURUSD",
        )
        self.assertEqual(h1, ())

    def test_m15_to_h1_completion_boundary(self) -> None:
        start = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m15 = [
            _m1_bar(start + timedelta(minutes=15 * index), close=1.1 + index * 0.01)
            for index in range(4)
        ]
        # Rewrite as proper M15-spaced bars with distinct OHLC
        m15 = [
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=15 * index),
                open=1.10 + index * 0.01,
                high=1.12 + index * 0.01,
                low=1.09 + index * 0.01,
                close=1.11 + index * 0.01,
                volume=1.0,
            )
            for index in range(4)
        ]
        self.assertEqual(
            aggregate_completed_bars(
                m15,
                source_timeframe="M15",
                target_timeframe="H1",
                asof=datetime(2026, 8, 29, 10, 45, tzinfo=timezone.utc),
                symbol="EURUSD",
            ),
            (),
        )
        h1 = aggregate_completed_bars(
            m15,
            source_timeframe="M15",
            target_timeframe="H1",
            asof=datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc),
            symbol="EURUSD",
        )
        self.assertEqual(len(h1), 1)
        self.assertEqual(h1[0].open, m15[0].open)
        self.assertEqual(h1[0].close, m15[-1].close)


class FutureMutationInvariantTests(unittest.TestCase):
    """Mandatory conceptual acceptance: future LTF mutation is invisible at T."""

    def test_future_m1_mutation_does_not_change_h1_features_at_1037(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        baseline = _m1_hour(hour, close_base=1.1000)
        # Prior completed hour so structure/features have something to work with.
        prior = _m1_hour(hour - timedelta(hours=1), close_base=1.0500)
        m1 = prior + baseline

        asof = datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc)
        config = default_feature_config()
        repo = FeatureRepository(config=config)

        before = repo.materialize(
            "EURUSD",
            {"M1": m1},
            entry_timeframe="H1",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )

        mutated = list(m1)
        for index, bar in enumerate(mutated):
            if ensure_utc(bar.timestamp) > asof:
                mutated[index] = Bar(
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    open=9.0,
                    high=99.0,
                    low=0.01,
                    close=50.0,
                    volume=999.0,
                )

        after = repo.materialize(
            "EURUSD",
            {"M1": mutated},
            entry_timeframe="H1",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )

        self.assertEqual(
            before.bars_by_timeframe.get("H1"),
            after.bars_by_timeframe.get("H1"),
        )
        before_struct = before.require_pack(PACK_STRUCTURE, StructurePack)
        after_struct = after.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(before_struct, StructurePack)
        assert isinstance(after_struct, StructurePack)
        self.assertEqual(
            before_struct.swings.by_timeframe.get("H1"),
            after_struct.swings.by_timeframe.get("H1"),
        )
        # Incomplete 10:00 H1 must be absent at 10:37.
        self.assertNotIn(
            datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            [bar.timestamp for bar in before.bars_by_timeframe.get("H1", ())],
        )

    def test_future_mutation_does_not_change_h1_indicator_at_t(self) -> None:
        # Build several completed H1 bars from M1, evaluate mid-hour.
        start = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        m1: list[Bar] = []
        for hour_offset in range(30):
            m1.extend(
                _m1_hour(
                    start + timedelta(hours=hour_offset),
                    close_base=1.0 + 0.01 * hour_offset,
                )
            )
        asof = datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc)
        repo = FeatureRepository()

        before = repo.materialize(
            "EURUSD",
            {"M1": m1},
            entry_timeframe="H1",
            asof=asof,
            pack_ids=(PACK_INDICATORS,),
        )
        mutated = [
            (
                Bar(
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    open=0.1,
                    high=100.0,
                    low=0.05,
                    close=80.0,
                    volume=1.0,
                )
                if ensure_utc(bar.timestamp) > asof
                else bar
            )
            for bar in m1
        ]
        after = repo.materialize(
            "EURUSD",
            {"M1": mutated},
            entry_timeframe="H1",
            asof=asof,
            pack_ids=(PACK_INDICATORS,),
        )
        ind_before = before.require_pack(PACK_INDICATORS, IndicatorPack)
        ind_after = after.require_pack(PACK_INDICATORS, IndicatorPack)
        assert isinstance(ind_before, IndicatorPack)
        assert isinstance(ind_after, IndicatorPack)
        self.assertEqual(ind_before.ema_fast_last, ind_after.ema_fast_last)
        self.assertEqual(ind_before.rsi_last, ind_after.rsi_last)
        self.assertEqual(ind_before.atr_last, ind_after.atr_last)


class FeatureRepositoryCausalTests(unittest.TestCase):
    def test_materialize_builds_completed_h1_from_m1(self) -> None:
        start = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(start) + _m1_hour(start + timedelta(hours=1))
        asof = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M1": m1},
            entry_timeframe="H1",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        h1 = context.bars_by_timeframe["H1"]
        self.assertEqual(len(h1), 2)
        self.assertTrue(all(bar_completion_time(bar, "H1") <= asof for bar in h1))

    def test_caller_incomplete_h1_cannot_silently_become_completed(self) -> None:
        # Caller supplies a fake "completed" H1 open at 10:00 while asof=10:37.
        fake_h1 = Bar(
            symbol="EURUSD",
            timestamp=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=1.0,
        )
        m15 = [
            Bar(
                symbol="EURUSD",
                timestamp=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
                + timedelta(minutes=15 * index),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1.0,
            )
            for index in range(3)
        ]
        asof = datetime(2026, 8, 29, 10, 37, tzinfo=timezone.utc)
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": m15, "H1": [fake_h1]},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        # Either omitted or rebuilt empty — must not keep high=2.0 incomplete bar.
        h1_bars = context.bars_by_timeframe.get("H1", ())
        self.assertTrue(
            all(bar.high != 2.0 for bar in h1_bars),
            msg=f"Incomplete caller H1 leaked: {h1_bars}",
        )
        self.assertTrue(
            all(bar_completion_time(bar, "H1") <= asof for bar in h1_bars)
        )

    def test_timezone_equivalent_asof_identical_aggregation(self) -> None:
        hour = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m1 = _m1_hour(hour - timedelta(hours=1)) + _m1_hour(hour)
        asof_utc = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
        asof_ny = asof_utc.astimezone(ZoneInfo("America/New_York"))
        repo = FeatureRepository()
        a = repo.materialize(
            "EURUSD",
            {"M1": m1},
            entry_timeframe="H1",
            asof=asof_utc,
            pack_ids=(PACK_STRUCTURE,),
        )
        b = repo.materialize(
            "EURUSD",
            {"M1": m1},
            entry_timeframe="H1",
            asof=asof_ny,
            pack_ids=(PACK_STRUCTURE,),
        )
        self.assertEqual(a.bars_by_timeframe["H1"], b.bars_by_timeframe["H1"])

    def test_asof_filters_entry_before_features(self) -> None:
        start = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
        m15 = [
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=15 * index),
                open=1.0 + index,
                high=1.0 + index,
                low=1.0 + index,
                close=1.0 + index,
                volume=1.0,
            )
            for index in range(8)
        ]
        asof = start + timedelta(minutes=30)  # includes 10:00 and 10:15 only? 
        # timestamp <= asof: 10:00, 10:15, 10:30
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": m15},
            entry_timeframe="M15",
            asof=asof,
            pack_ids=(PACK_STRUCTURE,),
        )
        entry = context.bars_by_timeframe["M15"]
        self.assertEqual(len(entry), 3)
        self.assertTrue(all(bar.timestamp <= asof for bar in entry))
        self.assertTrue(all(bar.close <= 3.0 for bar in entry))


class CrossTimeframeConsistencyTests(unittest.TestCase):
    def test_m15_to_h4_respects_completion(self) -> None:
        start = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
        # 16 M15 bars = one H4 when complete at 04:00
        m15 = [
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=15 * index),
                open=1.0,
                high=1.1,
                low=0.9,
                close=1.05,
                volume=1.0,
            )
            for index in range(16)
        ]
        early = prepare_causal_bars(
            {"M15": m15},
            entry_timeframe="M15",
            asof=datetime(2026, 8, 29, 3, 59, tzinfo=timezone.utc),
            higher_timeframes=("H4",),
            symbol="EURUSD",
        )
        self.assertNotIn("H4", early)

        done = prepare_causal_bars(
            {"M15": m15},
            entry_timeframe="M15",
            asof=datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc),
            higher_timeframes=("H4",),
            symbol="EURUSD",
        )
        self.assertIn("H4", done)
        self.assertEqual(len(done["H4"]), 1)


if __name__ == "__main__":
    unittest.main()
