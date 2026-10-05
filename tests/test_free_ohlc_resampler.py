"""Unit tests for research M1 → HTF resampler."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from models.bar import Bar
from research.free_ohlc.resampler import (
    bucket_start_utc,
    expected_open_minutes,
    is_fx_market_open_minute_utc,
    resample_bars,
)


def _m1(
    ts: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    vol: float | None = 1.0,
    symbol: str = "EURUSD",
) -> Bar:
    return Bar(symbol=symbol, timestamp=ts, open=o, high=h, low=l, close=c, volume=vol)


def _series(
    start: datetime,
    n: int,
    *,
    vol: float | None = 1.0,
) -> list[Bar]:
    bars: list[Bar] = []
    px = 1.1000
    for i in range(n):
        ts = start + timedelta(minutes=i)
        o = px
        h = px + 0.0002
        l = px - 0.0001
        c = px + 0.0001
        bars.append(_m1(ts, o, h, l, c, vol if vol is None else float(i + 1)))
        px = c
    return bars


class FreeOhlcResamplerTests(unittest.TestCase):
    def test_bucket_alignment(self) -> None:
        ts = datetime(2026, 1, 5, 10, 17, 0)  # Monday
        self.assertEqual(bucket_start_utc(ts, "M5"), datetime(2026, 1, 5, 10, 15))
        self.assertEqual(bucket_start_utc(ts, "M15"), datetime(2026, 1, 5, 10, 15))
        self.assertEqual(bucket_start_utc(ts, "M30"), datetime(2026, 1, 5, 10, 0))
        self.assertEqual(bucket_start_utc(ts, "H1"), datetime(2026, 1, 5, 10, 0))
        self.assertEqual(
            bucket_start_utc(datetime(2026, 1, 5, 9, 0), "H4"),
            datetime(2026, 1, 5, 8, 0),
        )
        self.assertEqual(
            bucket_start_utc(datetime(2026, 1, 5, 23, 59), "D1"),
            datetime(2026, 1, 5, 0, 0),
        )

    def test_fx_closure_weekend(self) -> None:
        # Friday 21:59 open, 22:00 closed
        self.assertTrue(is_fx_market_open_minute_utc(datetime(2026, 1, 2, 21, 59)))
        self.assertFalse(is_fx_market_open_minute_utc(datetime(2026, 1, 2, 22, 0)))
        # Saturday closed
        self.assertFalse(is_fx_market_open_minute_utc(datetime(2026, 1, 3, 12, 0)))
        # Sunday 21:59 closed, 22:00 open
        self.assertFalse(is_fx_market_open_minute_utc(datetime(2026, 1, 4, 21, 59)))
        self.assertTrue(is_fx_market_open_minute_utc(datetime(2026, 1, 4, 22, 0)))

    def test_m1_passthrough(self) -> None:
        bars = _series(datetime(2026, 1, 5, 10, 0), 3)
        out = resample_bars(bars, target_timeframe="M1")
        self.assertEqual(out.bars, tuple(bars))

    def test_m5_ohlc_and_volume_sum(self) -> None:
        start = datetime(2026, 1, 5, 10, 0)  # Monday
        bars = _series(start, 5, vol=1.0)
        # override volumes 1..5 via reconstruction
        bars = [
            _m1(start + timedelta(minutes=i), 1.0 + i * 0.001, 1.1, 0.9, 1.0 + i * 0.001, float(i + 1))
            for i in range(5)
        ]
        # fix OHLC properly
        bars = [
            _m1(start, 1.10, 1.12, 1.09, 1.11, 1),
            _m1(start + timedelta(minutes=1), 1.11, 1.13, 1.10, 1.12, 2),
            _m1(start + timedelta(minutes=2), 1.12, 1.14, 1.11, 1.13, 3),
            _m1(start + timedelta(minutes=3), 1.13, 1.15, 1.12, 1.14, 4),
            _m1(start + timedelta(minutes=4), 1.14, 1.16, 1.13, 1.15, 5),
        ]
        out = resample_bars(bars, target_timeframe="M5", volume_type="tick_volume")
        self.assertEqual(len(out.bars), 1)
        bar = out.bars[0]
        self.assertEqual(bar.timestamp, start)
        self.assertEqual(bar.open, 1.10)
        self.assertEqual(bar.high, 1.16)
        self.assertEqual(bar.low, 1.09)
        self.assertEqual(bar.close, 1.15)
        self.assertEqual(bar.volume, 15.0)

    def test_incomplete_m5_skipped(self) -> None:
        start = datetime(2026, 1, 5, 10, 0)
        bars = [
            _m1(start, 1.10, 1.11, 1.09, 1.105, 1),
            _m1(start + timedelta(minutes=1), 1.105, 1.12, 1.10, 1.11, 1),
            # missing minutes 2,3,4
        ]
        out = resample_bars(bars, target_timeframe="M5")
        self.assertEqual(len(out.bars), 0)
        self.assertEqual(out.stats.skipped_incomplete_buckets, 1)

    def test_allow_partial_emits_contiguous_span(self) -> None:
        start = datetime(2026, 1, 5, 10, 0)
        bars = [
            _m1(start, 1.10, 1.11, 1.09, 1.105, 1),
            _m1(start + timedelta(minutes=1), 1.105, 1.12, 1.10, 1.11, 2),
            _m1(start + timedelta(minutes=2), 1.11, 1.13, 1.10, 1.12, 3),
        ]
        out = resample_bars(bars, target_timeframe="M5", allow_partial=True)
        self.assertEqual(len(out.bars), 1)
        self.assertEqual(out.bars[0].open, 1.10)
        self.assertEqual(out.bars[0].close, 1.12)
        self.assertEqual(out.bars[0].volume, 6.0)

    def test_missing_volume_becomes_none(self) -> None:
        start = datetime(2026, 1, 5, 10, 0)
        bars = [
            _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, None)
            for i in range(5)
        ]
        out = resample_bars(bars, target_timeframe="M5", volume_type="none")
        self.assertEqual(len(out.bars), 1)
        self.assertIsNone(out.bars[0].volume)

    def test_m15_m30_h1(self) -> None:
        start = datetime(2026, 1, 5, 12, 0)
        for tf, n in (("M15", 15), ("M30", 30), ("H1", 60)):
            bars = [
                _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, 1.0)
                for i in range(n)
            ]
            out = resample_bars(bars, target_timeframe=tf)
            self.assertEqual(len(out.bars), 1, tf)
            self.assertEqual(out.bars[0].timestamp, start, tf)

    def test_h4_and_d1(self) -> None:
        # H4: 08:00-12:00 Monday needs 240 open minutes
        start = datetime(2026, 1, 5, 8, 0)
        bars = [
            _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, 1.0)
            for i in range(240)
        ]
        out = resample_bars(bars, target_timeframe="H4")
        self.assertEqual(len(out.bars), 1)
        self.assertEqual(out.bars[0].timestamp, start)

        # D1 Monday needs 1440 open minutes (no weekend inside Monday)
        day = datetime(2026, 1, 5, 0, 0)
        bars = [
            _m1(day + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, 1.0)
            for i in range(1440)
        ]
        out = resample_bars(bars, target_timeframe="D1")
        self.assertEqual(len(out.bars), 1)
        self.assertEqual(out.bars[0].timestamp, day)

    def test_weekend_does_not_invalidate_monday_h1(self) -> None:
        # Sunday 22:00-23:00 open hour should emit when complete
        start = datetime(2026, 1, 4, 22, 0)  # Sunday open
        bars = [
            _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, 1.0)
            for i in range(60)
        ]
        out = resample_bars(bars, target_timeframe="H1")
        self.assertEqual(len(out.bars), 1)
        # Saturday hour has zero expected open minutes → closed skip if presented
        sat = datetime(2026, 1, 3, 12, 0)
        # expected list empty
        self.assertEqual(expected_open_minutes(sat, "H1"), [])

    def test_duplicate_source_rejected(self) -> None:
        ts = datetime(2026, 1, 5, 10, 0)
        bars = [_m1(ts, 1.1, 1.2, 1.0, 1.15, 1), _m1(ts, 1.1, 1.2, 1.0, 1.15, 1)]
        with self.assertRaises(ValueError):
            resample_bars(bars, target_timeframe="M5")

    def test_deterministic_repeated_resample(self) -> None:
        start = datetime(2026, 1, 5, 10, 0)
        bars = [
            _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, float(i + 1))
            for i in range(15)
        ]
        a = resample_bars(bars, target_timeframe="M15")
        b = resample_bars(bars, target_timeframe="M15")
        self.assertEqual(a.bars, b.bars)

    def test_no_lookahead_future_bars(self) -> None:
        # Only first 5 minutes present → one M5; later orphan minutes in next bucket incomplete
        start = datetime(2026, 1, 5, 10, 0)
        bars = [
            _m1(start + timedelta(minutes=i), 1.1, 1.2, 1.0, 1.15, 1.0)
            for i in range(5)
        ] + [
            _m1(start + timedelta(minutes=7), 1.1, 1.2, 1.0, 1.15, 1.0)
        ]
        out = resample_bars(bars, target_timeframe="M5")
        self.assertEqual(len(out.bars), 1)
        self.assertEqual(out.bars[0].timestamp, start)
        self.assertEqual(out.stats.skipped_incomplete_buckets, 1)


if __name__ == "__main__":
    unittest.main()
