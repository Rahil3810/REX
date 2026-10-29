"""Focused tests for S002 Zone Breakout → Retest."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backtests.backtest_runner import BacktestRunner
from execution.factories import ZoneBreakoutRetestTradeSetupFactory
from execution.planner import TradePlanner
from execution.policies import FixedRiskRewardPolicy
from execution.sizers import FixedRiskSizer
from execution.validators import TradeSetupValidator
from models.account_context import AccountContext
from models.bar import Bar
from models.entry_model import EntryModel
from models.signal import Signal, SignalType
from models.trade_direction import TradeDirection
from models.trade_plan import TradePlanStatus
from models.zone import Zone, ZoneBook
from strategies.breakout_retest import BreakoutRetestState, S002_BreakoutRetest
from strategies.registry import build_default_registry

ZONE_LOW = 1.1500
ZONE_HIGH = 1.1520
BASE_TIME = datetime(2026, 6, 20, 12, 0, 0)


def _zone(
    zone_id: int = 1,
    name: str = "weekly_resistance",
    low: float = ZONE_LOW,
    high: float = ZONE_HIGH,
) -> Zone:
    return Zone(
        id=zone_id,
        name=name,
        low=low,
        high=high,
        timeframe="weekly",
        strength=8,
    )


def _book(*zones: Zone, symbol: str = "EURUSD") -> ZoneBook:
    return ZoneBook(symbol=symbol, zones=zones)


def _bar(
    index: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    symbol: str = "EURUSD",
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=BASE_TIME + timedelta(minutes=15 * index),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


class BreakoutRetestStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zone = _zone()
        self.strategy = S002_BreakoutRetest(
            zone_book=_book(self.zone),
            tolerance=0.0005,
            max_wait=5,
        )

    def test_bullish_breakout_emits_no_signal(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),  # breakout
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(signals, [])
        state = self.strategy._zone_states[1]
        self.assertEqual(state.status, BreakoutRetestState.WAITING_FOR_BULLISH_RETEST)
        self.assertAlmostEqual(state.broken_level or 0.0, ZONE_HIGH)

    def test_bullish_breakout_then_valid_retest(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),
            _bar(2, open_=1.1528, high=1.1532, low=1.1518, close=1.1525),  # retest
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, SignalType.RETEST_ABOVE)
        self.assertAlmostEqual(signals[0].price, 1.1525)
        self.assertEqual(signals[0].zone_id, 1)
        self.assertIn("Bullish breakout retest", signals[0].reason)
        self.assertIn("weekly_resistance", signals[0].reason)

    def test_bearish_breakout_then_valid_retest(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1505, high=1.1508, low=1.1485, close=1.1490),  # breakout
            _bar(2, open_=1.1492, high=1.1502, low=1.1488, close=1.1495),  # retest
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, SignalType.RETEST_BELOW)
        self.assertAlmostEqual(signals[0].price, 1.1495)

    def test_breakout_candle_cannot_be_its_own_retest(self) -> None:
        # Close above zone.high with a low that also touches the broken level.
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1518, close=1.1530),
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(signals, [])
        self.assertEqual(
            self.strategy._zone_states[1].status,
            BreakoutRetestState.WAITING_FOR_BULLISH_RETEST,
        )

    def test_retest_after_max_wait_does_not_trigger(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),  # breakout
        ]
        # Stay clearly above retest touch (broken_level + tolerance = 1.1525).
        # max_wait=5 → valid indices 2..6; index 7 is expired.
        for i in range(2, 7):
            bars.append(
                _bar(i, open_=1.1535, high=1.1545, low=1.1530, close=1.1540)
            )
        bars.append(
            _bar(7, open_=1.1528, high=1.1532, low=1.1518, close=1.1525)
        )
        signals = self.strategy.generate_signals(bars)
        retests = [s for s in signals if s.signal == SignalType.RETEST_ABOVE]
        self.assertEqual(retests, [])

    def test_bullish_invalidation_on_close_below_zone_low(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),
            _bar(2, open_=1.1520, high=1.1525, low=1.1480, close=1.1485),  # invalidate
            _bar(3, open_=1.1528, high=1.1532, low=1.1518, close=1.1525),  # would-be retest
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(
            [s.signal for s in signals if s.signal == SignalType.RETEST_ABOVE],
            [],
        )

    def test_bearish_invalidation_on_close_above_zone_high(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1505, high=1.1508, low=1.1485, close=1.1490),
            _bar(2, open_=1.1495, high=1.1535, low=1.1490, close=1.1530),  # invalidate
            _bar(3, open_=1.1492, high=1.1502, low=1.1488, close=1.1495),
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(
            [s.signal for s in signals if s.signal == SignalType.RETEST_BELOW],
            [],
        )

    def test_multiple_zones_independent_state(self) -> None:
        z1 = _zone(1, name="zone_a", low=1.1500, high=1.1520)
        z2 = _zone(2, name="zone_b", low=1.1600, high=1.1620)
        strategy = S002_BreakoutRetest(zone_book=_book(z1, z2), max_wait=5)
        bars = [
            # Inside z1; already below z2 → z2 enters bearish wait independently.
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),  # z1 bullish break
            _bar(2, open_=1.1528, high=1.1532, low=1.1518, close=1.1525),  # z1 retest
        ]
        signals = strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].zone_id, 1)
        self.assertEqual(signals[0].signal, SignalType.RETEST_ABOVE)
        # z1 completed; z2 still waiting independently (never retested).
        self.assertEqual(
            strategy._zone_states[1].status,
            BreakoutRetestState.IDLE,
        )
        self.assertEqual(
            strategy._zone_states[2].status,
            BreakoutRetestState.WAITING_FOR_BEARISH_RETEST,
        )

    def test_wrong_symbol_produces_no_signal(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510, symbol="GBPUSD"),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530, symbol="GBPUSD"),
            _bar(2, open_=1.1528, high=1.1532, low=1.1518, close=1.1525, symbol="GBPUSD"),
        ]
        self.assertEqual(self.strategy.generate_signals(bars), [])

    def test_reset_clears_pending_breakout_state(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),
        ]
        self.strategy.generate_signals(bars)
        self.assertEqual(
            self.strategy._zone_states[1].status,
            BreakoutRetestState.WAITING_FOR_BULLISH_RETEST,
        )
        self.strategy.reset()
        self.assertEqual(
            self.strategy._zone_states[1].status,
            BreakoutRetestState.IDLE,
        )
        self.assertIsNone(self.strategy._zone_states[1].broken_level)
        self.assertEqual(self.strategy._processed_count, 0)

    def test_bullish_retest_signal_price_is_close(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),
            _bar(2, open_=1.1528, high=1.1532, low=1.1518, close=1.1527),
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(signals[0].price, 1.1527)

    def test_bearish_retest_signal_price_is_close(self) -> None:
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1505, high=1.1508, low=1.1485, close=1.1490),
            _bar(2, open_=1.1492, high=1.1502, low=1.1488, close=1.1494),
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(signals[0].price, 1.1494)

    def test_registry_discovers_s002(self) -> None:
        registry = build_default_registry()
        cls = registry.get("S002")
        self.assertIs(cls, S002_BreakoutRetest)


class ZoneBreakoutRetestFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = BASE_TIME
        self.factory = ZoneBreakoutRetestTradeSetupFactory()
        self.candles = [
            Bar("EURUSD", self.ts, 1.1525, 1.1532, 1.1518, 1.1525),
        ]

    def test_retest_above_maps_to_long(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_ABOVE, 1, 1.1525, self.ts, "bullish retest"
        )
        setup = self.factory.create(signal, self.candles, "S002")
        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.direction, TradeDirection.LONG)

    def test_retest_below_maps_to_short(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_BELOW, 1, 1.1495, self.ts, "bearish retest"
        )
        candles = [Bar("EURUSD", self.ts, 1.1495, 1.1502, 1.1488, 1.1495)]
        setup = self.factory.create(signal, candles, "S002")
        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.direction, TradeDirection.SHORT)

    def test_long_stop_hint_is_bar_low(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_ABOVE, 1, 1.1525, self.ts, "bullish retest"
        )
        setup = self.factory.create(signal, self.candles, "S002")
        assert setup is not None
        self.assertAlmostEqual(setup.stop_hint or 0.0, 1.1518)

    def test_short_stop_hint_is_bar_high(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_BELOW, 1, 1.1495, self.ts, "bearish retest"
        )
        candles = [Bar("EURUSD", self.ts, 1.1495, 1.1502, 1.1488, 1.1495)]
        setup = self.factory.create(signal, candles, "S002")
        assert setup is not None
        self.assertAlmostEqual(setup.stop_hint or 0.0, 1.1502)

    def test_entry_model_is_next_candle_open(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_ABOVE, 1, 1.1525, self.ts, "bullish retest"
        )
        setup = self.factory.create(signal, self.candles, "S002")
        assert setup is not None
        self.assertEqual(setup.entry_model_hint, EntryModel.NEXT_CANDLE_OPEN)

    def test_factory_rejects_unrelated_signals(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "sweep"
        )
        self.assertIsNone(self.factory.create(signal, self.candles, "S002"))
        signal2 = Signal(
            "EURUSD", SignalType.BREAK_ABOVE, 1, 1.15, self.ts, "break"
        )
        self.assertIsNone(self.factory.create(signal2, self.candles, "S002"))

    def test_deterministic_setup_id(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_ABOVE, 1, 1.1525, self.ts, "bullish retest"
        )
        setup = self.factory.create(signal, self.candles, "S002")
        assert setup is not None
        expected = f"EURUSD_{self.ts.isoformat()}_retest_above"
        self.assertEqual(setup.setup_id, expected)
        self.assertEqual(setup.metadata["zone_id"], "1")
        self.assertEqual(setup.metadata["signal_type"], "retest_above")

    def test_factory_to_planner_path(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.RETEST_ABOVE, 1, 1.1525, self.ts, "bullish retest"
        )
        setup = self.factory.create(signal, self.candles, "S002")
        assert setup is not None
        validated = TradeSetupValidator().validate(setup)
        planner = TradePlanner(
            policy=FixedRiskRewardPolicy(r_multiple=2.0),
            sizer=FixedRiskSizer(),
            account=AccountContext(equity=10_000.0, risk_fraction=0.01),
        )
        plan = planner.plan(validated, self.candles)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.status, TradePlanStatus.PLANNED)
        self.assertAlmostEqual(plan.sl_price, 1.1518)
        self.assertAlmostEqual(plan.r_multiple, 2.0)


class BreakoutRetestIntegrationTests(unittest.TestCase):
    def test_backtest_runner_emits_retest_chronologically(self) -> None:
        strategy = S002_BreakoutRetest(zone_book=_book(_zone()), max_wait=5)
        bars = [
            _bar(0, open_=1.1510, high=1.1515, low=1.1505, close=1.1510),
            _bar(1, open_=1.1515, high=1.1535, low=1.1512, close=1.1530),  # breakout
            _bar(2, open_=1.1532, high=1.1540, low=1.1526, close=1.1535),  # continue
            _bar(3, open_=1.1528, high=1.1532, low=1.1518, close=1.1525),  # retest
        ]
        result = BacktestRunner().run(strategy, bars)
        retests = [
            o
            for o in result.signal_outcomes
            if o.signal_type == SignalType.RETEST_ABOVE
        ]
        self.assertEqual(len(retests), 1)
        self.assertEqual(retests[0].timestamp, bars[3].timestamp)
        self.assertAlmostEqual(retests[0].price, 1.1525)


if __name__ == "__main__":
    unittest.main()
