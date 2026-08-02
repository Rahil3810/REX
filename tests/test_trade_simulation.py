"""Unit and integration tests for REX Trade Simulation."""

import unittest
from datetime import datetime, timedelta
from collections.abc import Sequence

from models.bar import Bar
from models.signal import Signal, SignalType
from models.entry_model import EntryModel
from models.trade_setup import TradeSetup
from models.trade_plan import TradePlan
from models.trade_direction import TradeDirection
from models.position import Position
from models.closed_trade import ClosedTrade
from backtests.backtest_runner import BacktestRunner
from backtests.trade_simulator import TradeSimulator, calculate_pnl_r
from backtests.fill_models import FillModel, ConservativeOHLCFillModel
from execution.factories import SweepTradeSetupFactory
from execution.planner import TradePlanner
from execution.policies import FixedRiskRewardPolicy
from execution.sizers import FixedRiskSizer
from strategies.base_strategy import BaseStrategy


class MockSignalStrategy(BaseStrategy):
    strategy_id = "MOCK_SIG"
    strategy_name = "Mock Signal Strategy"
    description = "Test strategy to emit predefined signals."

    def __init__(self, signals_map: dict[datetime, list[Signal]]) -> None:
        self.signals_map = signals_map
        self.reset_called = False

    def reset(self) -> None:
        self.reset_called = True

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        current_bar = candles[-1]
        all_signals = self.signals_map.get(current_bar.timestamp, [])
        return [s for s in all_signals if s.symbol == current_bar.symbol]



def _planner(r_multiple: float = 2.0) -> TradePlanner:
    return TradePlanner(
        policy=FixedRiskRewardPolicy(r_multiple=r_multiple),
        sizer=FixedRiskSizer(),
    )


def _plan(
    *,
    symbol: str,
    direction: TradeDirection,
    sl_price: float,
    timestamp: datetime,
    strategy_id: str,
    setup_id: str = "id",
    r_multiple: float = 2.0,
    timeout_candles: int = 5,
    entry_price: float | None = None,
) -> TradePlan:
    if entry_price is None:
        entry_price = (
            sl_price + 0.01
            if direction == TradeDirection.LONG
            else sl_price - 0.01
        )
    setup = TradeSetup(
        setup_id=setup_id,
        symbol=symbol,
        direction=direction,
        strategy_id=strategy_id,
        timestamp=timestamp,
        reason="test",
        stop_hint=sl_price,
        entry_hint=entry_price,
        entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
    )
    risk = abs(entry_price - sl_price)
    tp = (
        entry_price + risk * r_multiple
        if direction == TradeDirection.LONG
        else entry_price - risk * r_multiple
    )
    return TradePlan(
        setup=setup,
        entry_model=EntryModel.NEXT_CANDLE_OPEN,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp,
        r_multiple=r_multiple,
        position_size=1.0,
        risk_amount=100.0,
        timeout_candles=timeout_candles,
        planned_at=timestamp,
    )


def _make_bar(symbol: str, timestamp: datetime, open_p: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_p,
        high=high,
        low=low,
        close=close,
    )


class TradeSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 6, 20, 12, 0, 0)

    def test_bullish_tp(self) -> None:
        """Verify long trade hits take profit."""
        # Entry at N+1 open (1.1500). SL is at 1.1400 (low of N).
        # TP is 1.1500 + 2 * (1.1500 - 1.1400) = 1.1700.
        # Candle N+1 high is 1.1800 (hits TP), low is 1.1450 (does not hit SL).
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1450, 1.1600),  # N+1 (Fill & Exit TP)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.exit_price, 1.1700)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_bullish_sl(self) -> None:
        """Verify long trade hits stop loss."""
        # Entry at N+1 open (1.1500). SL is at 1.1400. TP is at 1.1700.
        # Candle N+1 low is 1.1390 (hits SL), high is 1.1550 (does not hit TP).
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1390, 1.1420),  # N+1 (Fill & Exit SL)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "SL")
        self.assertAlmostEqual(trade.exit_price, 1.1400)
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_bearish_tp(self) -> None:
        """Verify short trade hits take profit."""
        # Entry at N+1 open (1.1500). SL is at 1.1600.
        # TP is 1.1500 - 2 * (1.1600 - 1.1500) = 1.1300.
        # Candle N+1 low is 1.1290 (hits TP), high is 1.1550 (does not hit SL).
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1290, 1.1350),  # N+1 (Fill & Exit TP)
        ]
        
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.exit_price, 1.1300)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_bearish_sl(self) -> None:
        """Verify short trade hits stop loss."""
        # Entry at N+1 open (1.1500). SL is at 1.1600. TP is at 1.1300.
        # Candle N+1 high is 1.1610 (hits SL), low is 1.1450 (does not hit TP).
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1610, 1.1450, 1.1590),  # N+1 (Fill & Exit SL)
        ]
        
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "SL")
        self.assertAlmostEqual(trade.exit_price, 1.1600)
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_signal_n_enters_only_on_n_plus_1(self) -> None:
        """Verify a signal at N does not execute entry at candle N."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1510, 1.1490, 1.1500),  # N+1 (Fills)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        runner = BacktestRunner()
        result = runner.run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.entry_time, self.base_time + timedelta(minutes=15)) # N+1

    def test_setup_generated_on_final_candle_is_cancelled(self) -> None:
        """Verify that a setup generated on the last dataset candle gets cancelled."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),  # Final candle N
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(result.cancelled_setups_count, 1)
        self.assertEqual(result.terminated_setups[0].reason, "CANCELLED_END_OF_DATA")

    def test_entry_candle_ambiguity(self) -> None:
        """Verify entry candle that hits both SL and TP resolves to conservative SL exit."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1300, 1.1500),  # N+1 (Spans SL and TP)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "AMBIGUITY")
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_normal_same_candle_ambiguity(self) -> None:
        """Verify open position spanning both SL and TP in the same candle resolves to SL exit."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1 (Fills)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1800, 1.1300, 1.1500),  # N+2 (Spans SL and TP)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "AMBIGUITY")
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_timeout_exact_candle_counting(self) -> None:
        """Verify max_hold_candles timeout resolves exactly on the final holding candle close."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal, SL=1.1400, TP=1.1700)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1510),  # N+1 (Holding 1)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1510, 1.1560, 1.1460, 1.1520),  # N+2 (Holding 2)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=45), 1.1520, 1.1570, 1.1470, 1.1530),  # N+3 (Holding 3 - Timeout close)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        strategy.max_hold_candles = 3
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TIMEOUT")
        self.assertAlmostEqual(trade.exit_price, 1.1530)  # Close of N+3
        self.assertEqual(trade.holding_duration_candles, 3)

    def test_force_close_end_of_data(self) -> None:
        """Verify open positions are force closed at final candle close."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1520),  # N+1 (Open position)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "FORCE_CLOSE_END_OF_DATA")
        self.assertAlmostEqual(trade.exit_price, 1.1520)  # Close of N+1

    def test_overlapping_signal_while_setup_pending(self) -> None:
        """Verify overlap policy ignores signals if a setup is already pending."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal 1)
        ]
        
        sig1 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "sig1")
        sig2 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "sig2")
        
        sim = TradeSimulator()
        factory = SweepTradeSetupFactory()
        planner = _planner()
        bars_seq = [bars[0]]

        setup1 = factory.create(sig1, bars_seq, "MOCK_SIG")
        plan1 = planner.plan(setup1, bars_seq)
        sim.add_plan(plan1)

        self.assertTrue(sim.has_active_lifecycle("MOCK_SIG", "EURUSD"))

        if not sim.has_active_lifecycle("MOCK_SIG", "EURUSD"):
            setup2 = factory.create(sig2, bars_seq, "MOCK_SIG")
            plan2 = planner.plan(setup2, bars_seq)
            sim.add_plan(plan2)

        self.assertEqual(len(sim.pending_plans[("MOCK_SIG", "EURUSD")]), 1)

    def test_overlapping_signal_while_position_open(self) -> None:
        """Verify overlap policy ignores signals if a position is open."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal 1)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1455, 1.1500),  # N+1 (Fills, Signal 2)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1550, 1.1455, 1.1500),  # N+2
        ]
        
        sig1 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "sig1")
        sig2 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time + timedelta(minutes=15), "sig2")
        
        strategy = MockSignalStrategy({
            self.base_time: [sig1],
            self.base_time + timedelta(minutes=15): [sig2],
        })
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        self.assertEqual(result.closed_trades[0].entry_time, self.base_time + timedelta(minutes=15))

    def test_isolation_between_different_strategies(self) -> None:
        """Verify that different strategies on the same symbol are isolated by strategy_id."""
        sim = TradeSimulator()
        self.assertFalse(sim.has_active_lifecycle("STRAT_A", "EURUSD"))

    def test_isolation_between_symbols(self) -> None:
        """Verify that same strategy across different symbols remains isolated."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("GBPUSD", self.base_time, 1.2500, 1.2510, 1.2400, 1.2500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1450, 1.1600),  # N+1 (EUR TP)
            _make_bar("GBPUSD", self.base_time + timedelta(minutes=15), 1.2500, 1.2510, 1.2450, 1.2500),  # N+1 (GBP Open)
        ]
        
        sig_eur = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "eur")
        sig_gbp = Signal("GBPUSD", SignalType.BULLISH_SWEEP, 0, 1.2500, self.base_time, "gbp")
        
        strategy = MockSignalStrategy({
            self.base_time: [sig_eur, sig_gbp]
        })
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 2)
        eur_trade = [t for t in result.closed_trades if t.symbol == "EURUSD"][0]
        gbp_trade = [t for t in result.closed_trades if t.symbol == "GBPUSD"][0]
        
        self.assertEqual(eur_trade.close_reason, "TP")
        self.assertEqual(gbp_trade.close_reason, "FORCE_CLOSE_END_OF_DATA")

    def test_simulator_reset_between_runs(self) -> None:
        """Verify simulator reset clears all state."""
        sim = TradeSimulator()
        plan = _plan(symbol="EURUSD", direction=TradeDirection.LONG, sl_price=1.1400, timestamp=self.base_time, strategy_id="STRAT_A")
        sim.add_plan(plan)
        self.assertTrue(sim.has_active_lifecycle("STRAT_A", "EURUSD"))
        
        sim.reset()
        self.assertFalse(sim.has_active_lifecycle("STRAT_A", "EURUSD"))

    def test_strategy_reset_between_runs(self) -> None:
        """Verify strategy reset is called at start of runner execution."""
        bars = [_make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500)]
        strategy = MockSignalStrategy({})
        self.assertFalse(strategy.reset_called)
        
        BacktestRunner().run(strategy, bars)
        self.assertTrue(strategy.reset_called)

    def test_existing_signal_only_behavior_unchanged(self) -> None:
        """Verify that existing signal-only behavior is preserved when simulate_trades=False."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),  # N (Signal)
        ]
        
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=False)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(len(result.signal_outcomes), 1)
        self.assertEqual(result.signal_outcomes[0].signal_type, SignalType.BULLISH_SWEEP)

    def test_bullish_fill_tp_r_units_exact_gap(self) -> None:
        """Verify that a LONG gap between signal close and N+1 open still realizes exact configured TP R."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1600, 1.2100, 1.1500, 1.1800),  # N+1
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.entry_price, 1.1600)
        self.assertAlmostEqual(trade.exit_price, 1.2000)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_bearish_fill_tp_r_units_exact_gap(self) -> None:
        """Verify that a SHORT gap between signal close and N+1 open still realizes exact configured TP R."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1400, 1.1500, 1.0900, 1.1200),  # N+1
        ]
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(2.0))
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.entry_price, 1.1400)
        self.assertAlmostEqual(trade.exit_price, 1.1000)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_different_r_multiples(self) -> None:
        """Verify that 1.0R, 1.5R, 2.0R, 3.0R record exactly the configured R multiples."""
        multiples = [1.0, 1.5, 2.0, 3.0]
        for mult in multiples:
            bars = [
                _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),
                _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.2000, 1.1450, 1.1600),
            ]
            signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
            strategy = MockSignalStrategy({self.base_time: [signal]})
            
            result = BacktestRunner().run(strategy, bars, simulate_trades=True, trade_planner=_planner(mult))
            
            trade = result.closed_trades[0]
            self.assertEqual(trade.close_reason, "TP")
            self.assertAlmostEqual(trade.pnl_r, mult)

    def test_invalid_sl_relative_to_fill_rejected(self) -> None:
        """Verify that invalid structural SL relative to actual fill is rejected safely."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal, SL=1.1400)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1300, 1.1550, 1.1290, 1.1450),  # N+1 (Gaps below SL)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(result.rejected_setups_count, 1)
        self.assertEqual(result.terminated_setups[0].reason, "REJECTED_INVALID_ENTRY")

    def test_lifecycle_strategy_and_symbol_isolation(self) -> None:
        """Verify that lifecycle ownership is isolated by (strategy_id, symbol)."""
        sim = TradeSimulator()
        plan_a = _plan(symbol="EURUSD", direction=TradeDirection.LONG, sl_price=1.1400, timestamp=self.base_time, strategy_id="STRAT_A", setup_id="id1")
        sim.add_plan(plan_a)
        
        self.assertTrue(sim.has_active_lifecycle("STRAT_A", "EURUSD"))
        self.assertFalse(sim.has_active_lifecycle("STRAT_B", "EURUSD"))
        self.assertFalse(sim.has_active_lifecycle("STRAT_A", "GBPUSD"))

    def test_cancelled_and_expired_setups_reporting(self) -> None:
        """Verify natural expiration and end-of-dataset cancellation reporting."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(result.cancelled_setups_count, 1)
        self.assertEqual(result.expired_setups_count, 0)
        self.assertEqual(result.terminated_setups[0].reason, "CANCELLED_END_OF_DATA")
        
        payload = result.to_dict()
        self.assertEqual(len(payload["terminated_setups"]), 1)
        self.assertEqual(payload["terminated_setups"][0]["reason"], "CANCELLED_END_OF_DATA")

    def test_unsupported_signals_are_skipped(self) -> None:
        """Verify that unsupported signal types are skipped without defaults."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),
        ]
        signal = Signal("EURUSD", SignalType.CLOSE_OUTSIDE, 1, 1.1500, self.base_time, "unsupported")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(len(result.terminated_setups), 0)

    def test_supported_signals_directions(self) -> None:
        """Verify BULLISH_SWEEP creates LONG and BEARISH_SWEEP creates SHORT setup."""
        bars = [_make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500)]
        factory = SweepTradeSetupFactory()
        planner = _planner()

        bull_sig = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "bull")
        setup_bull = factory.create(bull_sig, bars, "MOCK")
        plan_bull = planner.plan(setup_bull, bars)
        self.assertEqual(setup_bull.direction, TradeDirection.LONG)
        self.assertAlmostEqual(setup_bull.stop_hint, 1.1400)
        self.assertAlmostEqual(plan_bull.sl_price, 1.1400)

        bear_sig = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "bear")
        setup_bear = factory.create(bear_sig, bars, "MOCK")
        plan_bear = planner.plan(setup_bear, bars)
        self.assertEqual(setup_bear.direction, TradeDirection.SHORT)
        self.assertAlmostEqual(setup_bear.stop_hint, 1.1510)
        self.assertAlmostEqual(plan_bear.sl_price, 1.1510)

    def test_adverse_long_gap_through_sl(self) -> None:
        """Verify that an adverse LONG gap through SL uses bar.open and realizes worse than -1R."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1 (Fill at 1.1500)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1300, 1.1350, 1.1290, 1.1310),  # N+2 (Gaps through SL on open)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "SL")
        self.assertAlmostEqual(trade.exit_price, 1.1300)
        self.assertAlmostEqual(trade.pnl_r, -2.0)

    def test_adverse_short_gap_through_sl(self) -> None:
        """Verify that an adverse SHORT gap through SL uses bar.open and realizes worse than -1R."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1 (Fill at 1.1500)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1700, 1.1750, 1.1690, 1.1710),  # N+2 (Gaps through SL on open)
        ]
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "SL")
        self.assertAlmostEqual(trade.exit_price, 1.1700)
        self.assertAlmostEqual(trade.pnl_r, -2.0)

    def test_favorable_long_gap_through_tp(self) -> None:
        """Verify that a favorable LONG gap through TP uses the TP price under conservative limit fill logic."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1800, 1.1850, 1.1790, 1.1810),  # N+2 (Gaps through TP on open)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.exit_price, 1.1700)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_favorable_short_gap_through_tp(self) -> None:
        """Verify that a favorable SHORT gap through TP uses the TP price under conservative limit fill logic."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1200, 1.1250, 1.1190, 1.1210),  # N+2 (Gaps through TP on open)
        ]
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.exit_price, 1.1300)
        self.assertAlmostEqual(trade.pnl_r, 2.0)

    def test_invalid_long_entry_rejected(self) -> None:
        """Verify that invalid LONG entry structure is rejected as REJECTED_INVALID_ENTRY."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1350, 1.1500, 1.1300, 1.1400),  # N+1 (Gaps below SL)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(result.rejected_setups_count, 1)
        self.assertEqual(result.terminated_setups[0].reason, "REJECTED_INVALID_ENTRY")

    def test_invalid_short_entry_rejected(self) -> None:
        """Verify that invalid SHORT entry structure is rejected as REJECTED_INVALID_ENTRY."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1600, 1.1490, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1650, 1.1700, 1.1500, 1.1600),  # N+1 (Gaps above SL)
        ]
        signal = Signal("EURUSD", SignalType.BEARISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        self.assertEqual(len(result.closed_trades), 0)
        self.assertEqual(result.rejected_setups_count, 1)
        self.assertEqual(result.terminated_setups[0].reason, "REJECTED_INVALID_ENTRY")

    def test_custom_fill_model_injection(self) -> None:
        """Verify that a custom FillModel can be injected and overrides entry/exit prices."""
        class CustomFillModel:
            def check_entry(self, plan: TradePlan, bar: Bar) -> float | None:
                return 1.2000

            def check_exit(self, position: Position, bar: Bar) -> tuple[float, str] | None:
                return 1.2500, "TP"

        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True, fill_model=CustomFillModel())
        
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertAlmostEqual(trade.entry_price, 1.2000)
        self.assertAlmostEqual(trade.exit_price, 1.2500)


class SignalLifecycleAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 6, 20, 12, 0, 0)

    def test_reconciliation_zero_diff_normal_flow(self) -> None:
        """Verify that a normal trade flow reconciles with exactly zero difference."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1450, 1.1600),  # N+1 (Fill & TP exit)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        sig_recon = result.reconcile_signals()
        self.assertEqual(sig_recon["generated"], 1)
        self.assertEqual(sig_recon["accepted"], 1)
        self.assertEqual(sig_recon["ignored"], 0)
        self.assertEqual(sig_recon["rejected"], 0)
        self.assertEqual(sig_recon["difference"], 0)
        
        exec_recon = result.reconcile_execution()
        self.assertEqual(exec_recon["accepted"], 1)
        self.assertEqual(exec_recon["closed"], 1)
        self.assertEqual(exec_recon["expired"], 0)
        self.assertEqual(exec_recon["rejected"], 0)
        self.assertEqual(exec_recon["cancelled"], 0)
        self.assertEqual(exec_recon["active"], 0)
        self.assertEqual(exec_recon["difference"], 0)

    def test_reconciliation_ignored_overlap(self) -> None:
        """Verify overlap-rejected signals are counted explicitly and reconcile."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal 1)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1550, 1.1450, 1.1500),  # N+1 (Signal 2)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1800, 1.1450, 1.1600),  # N+2
        ]
        sig1 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "sig1")
        sig2 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time + timedelta(minutes=15), "sig2")
        strategy = MockSignalStrategy({
            self.base_time: [sig1],
            self.base_time + timedelta(minutes=15): [sig2],
        })
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        sig_recon = result.reconcile_signals()
        self.assertEqual(sig_recon["generated"], 2)
        self.assertEqual(sig_recon["accepted"], 1)
        self.assertEqual(sig_recon["ignored"], 1)
        self.assertEqual(sig_recon["rejected"], 0)
        self.assertEqual(sig_recon["difference"], 0)

    def test_reconciliation_unsupported_signal(self) -> None:
        """Verify unsupported signals are counted explicitly at policy boundary and reconcile."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
        ]
        sig = Signal("EURUSD", SignalType.CLOSE_OUTSIDE, 1, 1.1500, self.base_time, "unsupported")
        strategy = MockSignalStrategy({self.base_time: [sig]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        sig_recon = result.reconcile_signals()
        self.assertEqual(sig_recon["generated"], 1)
        self.assertEqual(sig_recon["accepted"], 0)
        self.assertEqual(sig_recon["ignored"], 0)
        self.assertEqual(sig_recon["rejected"], 1)
        self.assertEqual(sig_recon["difference"], 0)

    def test_reconciliation_invalid_rejection_no_double_count(self) -> None:
        """Verify rejected invalid entries are recorded without double counting."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),  # N (Signal)
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1350, 1.1500, 1.1300, 1.1400),  # N+1 (Gaps below SL)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        exec_recon = result.reconcile_execution()
        self.assertEqual(exec_recon["accepted"], 1)
        self.assertEqual(exec_recon["closed"], 0)
        self.assertEqual(exec_recon["expired"], 0)
        self.assertEqual(exec_recon["rejected"], 1)
        self.assertEqual(exec_recon["cancelled"], 0)
        self.assertEqual(exec_recon["active"], 0)
        self.assertEqual(exec_recon["difference"], 0)

    def test_reconciliation_final_candle_cancelled(self) -> None:
        """Verify final-candle signals reconcile correctly as cancelled end-of-data."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),  # N (Final bar, signal generated)
        ]
        signal = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [signal]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        exec_recon = result.reconcile_execution()
        self.assertEqual(exec_recon["accepted"], 1)
        self.assertEqual(exec_recon["closed"], 0)
        self.assertEqual(exec_recon["rejected"], 0)
        self.assertEqual(exec_recon["cancelled"], 1)
        self.assertEqual(exec_recon["active"], 0)
        self.assertEqual(exec_recon["difference"], 0)

    def test_reconciliation_multi_symbol_isolation(self) -> None:
        """Verify multi-symbol accounting remains isolated and correct."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),
            _make_bar("GBPUSD", self.base_time, 1.2500, 1.2510, 1.2400, 1.2500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1450, 1.1600),  # EUR TP
            _make_bar("GBPUSD", self.base_time + timedelta(minutes=15), 1.2500, 1.2510, 1.2450, 1.2500),  # GBP active
        ]
        sig_eur = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "eur")
        sig_gbp = Signal("GBPUSD", SignalType.BULLISH_SWEEP, 0, 1.2500, self.base_time, "gbp")
        strategy = MockSignalStrategy({
            self.base_time: [sig_eur, sig_gbp]
        })
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        
        sig_recon = result.reconcile_signals()
        self.assertEqual(sig_recon["difference"], 0)
        
        exec_recon = result.reconcile_execution()
        self.assertEqual(exec_recon["difference"], 0)
        self.assertEqual(exec_recon["closed"], 2)

    def test_reconciliation_reset_between_runs(self) -> None:
        """Verify repeated backtest runs reset all accounting state."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1400, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1800, 1.1450, 1.1600),
        ]
        sig = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [sig]})
        
        runner = BacktestRunner()
        res1 = runner.run(strategy, bars, simulate_trades=True)
        self.assertEqual(res1.reconcile_signals()["generated"], 1)
        
        strategy_empty = MockSignalStrategy({})
        res2 = runner.run(strategy_empty, bars, simulate_trades=True)
        self.assertEqual(res2.reconcile_signals()["generated"], 0)

    def test_signal_only_mode_unchanged_accounting(self) -> None:
        """Verify that signal-only mode remains unchanged and reconciles."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
        ]
        sig = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.1500, self.base_time, "test")
        strategy = MockSignalStrategy({self.base_time: [sig]})
        
        result = BacktestRunner().run(strategy, bars, simulate_trades=False)
        self.assertEqual(result.total_signals, 1)
        self.assertEqual(result.accepted_setups_count, 0)
        self.assertEqual(result.ignored_active_lifecycle_count, 0)


if __name__ == "__main__":
    unittest.main()
