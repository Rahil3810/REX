"""P1-6: structural swing-referenced BOS (swing_bos_v1)."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from core.features.config import SwingDetectionConfig
from core.features.generators.bos import (
    BOSDirection,
    detect_swing_bos,
    detect_swing_bos_series,
)
from core.features.generators.swings import (
    SwingEvent,
    SwingGenerator,
    SwingKind,
    make_swing_id,
)
from core.features.types import METHOD_STRUCTURE_SWING_BOS_V1
from core.market import require_instrument
from models.bar import Bar


def _ts(minute: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute)


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


def _swing(
    kind: SwingKind,
    *,
    index: int,
    price: float,
    confirmation_index: int,
    timeframe: str = "M15",
) -> SwingEvent:
    return SwingEvent(
        id=make_swing_id(timeframe, kind, index),
        timeframe=timeframe,
        kind=kind,
        price=price,
        index=index,
        timestamp=_ts(index),
        confirmation_index=confirmation_index,
        confirmation_time=_ts(confirmation_index),
    )


def _golden_bars() -> list[Bar]:
    highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
    lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
    return [
        _bar(i, high=float(h), low=float(l))
        for i, (h, l) in enumerate(zip(highs, lows, strict=True))
    ]


class StructuralBOSBullishBearishTests(unittest.TestCase):
    def test_bullish_bos_closes_above_confirmed_structural_high(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=12.5))
        result = detect_swing_bos(bars, [high])
        self.assertTrue(result.detected)
        self.assertTrue(result.bullish)
        assert result.event is not None
        self.assertEqual(result.event.direction, BOSDirection.BULLISH)
        self.assertEqual(result.event.broken_swing.id, high.id)
        self.assertEqual(result.event.break_close, 12.5)

    def test_bearish_bos_closes_below_confirmed_structural_low(self) -> None:
        bars = [_bar(i, high=12, low=10, close=11) for i in range(6)]
        low = _swing(SwingKind.LOW, index=2, price=9.0, confirmation_index=4)
        bars.append(_bar(6, high=10, low=8, close=8.5))
        result = detect_swing_bos(bars, [low])
        self.assertTrue(result.detected)
        self.assertTrue(result.bearish)
        assert result.event is not None
        self.assertEqual(result.event.direction, BOSDirection.BEARISH)
        self.assertEqual(result.event.broken_swing.price, 9.0)

    def test_exact_equality_with_swing_price_is_not_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=12.0))
        result = detect_swing_bos(bars, [high])
        self.assertFalse(result.detected)

    def test_wick_only_break_is_not_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=11.5))
        result = detect_swing_bos(bars, [high])
        self.assertFalse(result.detected)


class StructuralVsLookbackTests(unittest.TestCase):
    def test_non_structural_lookback_max_does_not_replace_structural_swing(self) -> None:
        """structural HIGH=14, lookback HIGH=16, close=15 → BOS @ 14."""
        bars = _golden_bars()
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        swings = gen.generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        ).by_timeframe["M15"]
        self.assertEqual(swings.swing_highs, (15.0, 14.0))
        self.assertNotIn(16.0, swings.swing_highs)

        bars.append(_bar(11, high=15.5, low=10, close=15.0))
        result = detect_swing_bos(bars, swings.swings)
        self.assertTrue(result.detected)
        assert result.event is not None
        self.assertEqual(result.event.broken_swing.price, 14.0)
        self.assertEqual(result.event.broken_swing.id, "M15:high:6")

    def test_structural_swing_broken_even_when_not_lookback_max(self) -> None:
        # Same scenario as above — most recent structural high (14) is below
        # lookback max (16); close 15 breaks structure without breaking lookback max.
        bars = _golden_bars()
        swings = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        ).by_timeframe["M15"]
        bars.append(_bar(11, high=15.2, low=10, close=15.0))
        lookback_max = max(b.high for b in bars[:-1][-10:])
        self.assertEqual(lookback_max, 16.0)
        self.assertLess(bars[-1].close, lookback_max)
        result = detect_swing_bos(bars, swings.swings)
        self.assertTrue(result.detected)
        assert result.event is not None
        self.assertEqual(result.event.broken_swing.price, 14.0)


class StructuralBOSResultFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        self.bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        self.bars.append(_bar(6, high=13, low=10, close=12.5))
        self.result = detect_swing_bos(self.bars, [self.high])

    def test_result_references_exact_swing_event_id(self) -> None:
        assert self.result.event is not None
        self.assertEqual(self.result.event.broken_swing.id, self.high.id)

    def test_result_includes_swing_price(self) -> None:
        assert self.result.event is not None
        self.assertEqual(self.result.event.broken_swing.price, 12.0)

    def test_result_includes_source_index_and_timestamp(self) -> None:
        assert self.result.event is not None
        self.assertEqual(self.result.event.broken_swing.index, 2)
        self.assertEqual(self.result.event.broken_swing.timestamp, _ts(2))

    def test_result_includes_confirmation_time(self) -> None:
        assert self.result.event is not None
        self.assertEqual(self.result.event.broken_swing.confirmation_time, _ts(4))

    def test_result_includes_break_candle_index_and_timestamp(self) -> None:
        assert self.result.event is not None
        self.assertEqual(self.result.event.break_index, 6)
        self.assertEqual(self.result.event.break_time, _ts(6))
        self.assertEqual(self.result.event.break_close, 12.5)

    def test_method_id_is_swing_bos_v1(self) -> None:
        self.assertEqual(self.result.method_id, str(METHOD_STRUCTURE_SWING_BOS_V1))
        assert self.result.event is not None
        self.assertEqual(self.result.event.method_id, "swing_bos_v1")


class StructuralBOSCausalityTests(unittest.TestCase):
    def test_break_candle_cannot_use_swing_confirmed_on_same_candle(self) -> None:
        # confirmation_index == break_index → ineligible (need confirmation_index < j)
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(4)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(4, high=13, low=10, close=12.5))  # break_index == 4
        self.assertEqual(len(bars) - 1, 4)
        result = detect_swing_bos(bars, [high])
        self.assertFalse(result.detected)

    def test_unconfirmed_future_swing_cannot_be_used(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(5)]
        # Swing would confirm at index 6, but we evaluate break at index 4
        future_high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=6)
        bars.append(_bar(4, high=13, low=10, close=12.5))
        # Only bars through index 4; swing confirmation is in the future
        result = detect_swing_bos(bars, [future_high])
        self.assertFalse(result.detected)

    def test_no_confirmed_swings_yields_no_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(5)]
        bars.append(_bar(5, high=20, low=10, close=19.0))
        result = detect_swing_bos(bars, [])
        self.assertFalse(result.detected)

    def test_future_bar_mutation_cannot_change_already_confirmed_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=12.5))
        first = detect_swing_bos(bars, [high])
        self.assertTrue(first.detected)
        assert first.event is not None
        snapshot = copy.deepcopy(first.event)

        # Mutate / append future bars; historical BOS on index 6 must stay identical
        bars.append(_bar(7, high=20, low=10, close=19.0))
        bars.append(_bar(8, high=5, low=1, close=2.0))
        series = detect_swing_bos_series(bars, [high])
        historical = [e for e in series if e.break_index == 6]
        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0], snapshot)

    def test_deterministic_repeated_materialization(self) -> None:
        bars = _golden_bars() + [_bar(11, high=15.5, low=10, close=15.0)]
        swings = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
            {"M15": bars[:-1]},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
        ).by_timeframe["M15"].swings
        a = detect_swing_bos_series(bars, swings)
        b = detect_swing_bos_series(bars, swings)
        self.assertEqual(a, b)
        self.assertEqual(detect_swing_bos(bars, swings), detect_swing_bos(bars, swings))


class StructuralBOSDirectionIndependenceTests(unittest.TestCase):
    def test_bullish_bos_does_not_require_caller_bullish_flag(self) -> None:
        # API has no bullish/bearish parameters — direction from broken swing kind.
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=12.5))
        result = detect_swing_bos(bars, [high])
        self.assertTrue(result.bullish)
        self.assertFalse(result.bearish)

    def test_bearish_bos_does_not_require_caller_bearish_flag(self) -> None:
        bars = [_bar(i, high=12, low=10, close=11) for i in range(6)]
        low = _swing(SwingKind.LOW, index=2, price=9.0, confirmation_index=4)
        bars.append(_bar(6, high=10, low=8, close=8.5))
        result = detect_swing_bos(bars, [low])
        self.assertTrue(result.bearish)
        self.assertFalse(result.bullish)


class StructuralBOSConsumptionTests(unittest.TestCase):
    def test_repeated_closes_above_same_swing_do_not_emit_duplicate_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(6)]
        high = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        bars.append(_bar(6, high=13, low=10, close=12.5))
        bars.append(_bar(7, high=14, low=11, close=13.0))
        bars.append(_bar(8, high=15, low=12, close=14.0))
        series = detect_swing_bos_series(bars, [high])
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0].break_index, 6)
        self.assertEqual(series[0].broken_swing.id, high.id)

        # Latest candle alone is not a new BOS
        latest = detect_swing_bos(bars, [high])
        self.assertFalse(latest.detected)
        self.assertEqual(len(latest.series), 1)

    def test_later_structural_swing_can_generate_later_bos(self) -> None:
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(10)]
        high_a = _swing(SwingKind.HIGH, index=2, price=12.0, confirmation_index=4)
        high_b = _swing(SwingKind.HIGH, index=7, price=13.0, confirmation_index=9)
        # Break A at index 6
        bars[6] = _bar(6, high=13, low=10, close=12.5)
        # After B confirms at 9, break B at 10
        bars.append(_bar(10, high=14, low=11, close=13.5))
        series = detect_swing_bos_series(bars, [high_a, high_b])
        self.assertEqual(len(series), 2)
        self.assertEqual(series[0].broken_swing.id, high_a.id)
        self.assertEqual(series[0].break_index, 6)
        self.assertEqual(series[1].broken_swing.id, high_b.id)
        self.assertEqual(series[1].break_index, 10)


class StructuralBOSMostRecentSwingTests(unittest.TestCase):
    def test_selects_most_recent_confirmed_high_not_highest_price(self) -> None:
        # HIGH A price=15 index=5; HIGH B price=14 index=10 — break uses B
        bars = [_bar(i, high=10, low=9, close=9.5) for i in range(14)]
        high_a = _swing(SwingKind.HIGH, index=5, price=15.0, confirmation_index=7)
        high_b = _swing(SwingKind.HIGH, index=10, price=14.0, confirmation_index=12)
        bars.append(_bar(14, high=16, low=10, close=15.5))
        result = detect_swing_bos(bars, [high_a, high_b])
        self.assertTrue(result.detected)
        assert result.event is not None
        self.assertEqual(result.event.broken_swing.id, high_b.id)
        self.assertEqual(result.event.broken_swing.price, 14.0)


class ExistingSwingTestsUnchangedSmoke(unittest.TestCase):
    """Golden / causal swing vectors remain as established in P1-5."""

    def test_golden_swing_prices_unchanged(self) -> None:
        bars = _golden_bars()
        tf = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        ).by_timeframe["M15"]
        self.assertEqual(tf.swing_highs, (15.0, 14.0))
        self.assertEqual(tf.swing_lows, (7.0, 6.0))

    def test_causal_asof_filter_still_excludes_unconfirmed(self) -> None:
        bars = _golden_bars()
        gen = SwingGenerator(SwingDetectionConfig(2, 2, 2))
        # Confirm SH@2 at index 4 (timestamp minute 4)
        asof = _ts(4)
        tf = gen.generate(
            {"M15": bars},
            require_instrument("EURUSD"),
            entry_timeframe="M15",
            asof=asof,
        ).by_timeframe["M15"]
        # At confirmation of first high (15), second high (14) not yet confirmed
        self.assertEqual(tf.swing_highs, (15.0,))


if __name__ == "__main__":
    unittest.main()
