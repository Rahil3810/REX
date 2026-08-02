"""Adversarial QA validation of the REX execution architecture.

Mindset: try to break the pipeline. These tests encode expected contracts and
document intentional gaps vs unexpected defects.
"""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from backtests.backtest_runner import BacktestRunner
from backtests.trade_simulator import TradeSimulator, calculate_pnl_r
from execution.factories import SweepTradeSetupFactory
from execution.planner import TradePlanner
from execution.policies import FixedRiskRewardPolicy
from execution.sizers import FixedRiskSizer
from execution.validators import TradeSetupValidationError, TradeSetupValidator
from models.account_context import AccountContext
from models.bar import Bar
from models.entry_model import EntryModel
from models.signal import Signal, SignalType
from models.trade_direction import TradeDirection
from models.trade_plan import TradePlan, TradePlanStatus
from models.trade_setup import TradeSetup
from strategies.base_strategy import BaseStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy


def _bar(
    ts: datetime,
    *,
    symbol: str = "EURUSD",
    o: float = 1.15,
    h: float = 1.16,
    low: float = 1.14,
    c: float = 1.15,
) -> Bar:
    return Bar(symbol, ts, o, h, low, c)


class MockMapStrategy(BaseStrategy):
    strategy_id = "QA_MOCK"
    strategy_name = "QA Mock"
    description = "Emits a fixed signal map for QA."

    def __init__(self, signals_map: dict[datetime, list[Signal]]) -> None:
        self.signals_map = signals_map

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        current = candles[-1]
        return [
            s
            for s in self.signals_map.get(current.timestamp, [])
            if s.symbol == current.symbol
        ]


class FactoryComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)
        self.factory = SweepTradeSetupFactory()

    def test_bullish_mapping_fields(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "bull reason"
        )
        candles = [_bar(self.ts, low=1.14, h=1.16, c=1.15)]
        setup = self.factory.create(signal, candles, "S008")
        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.direction, TradeDirection.LONG)
        self.assertEqual(setup.entry_hint, 1.15)
        self.assertEqual(setup.stop_hint, 1.14)
        self.assertIsNone(setup.target_hint)
        self.assertIsNone(setup.timeout_candles)
        self.assertEqual(setup.entry_model_hint, EntryModel.NEXT_CANDLE_OPEN)
        self.assertEqual(setup.metadata.get("signal_type"), "bullish_sweep")
        self.assertEqual(setup.reason, "bull reason")

    def test_empty_candles_rejected(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "x"
        )
        self.assertIsNone(self.factory.create(signal, [], "S008"))

    def test_non_sweep_rejected(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BREAK_ABOVE, 1, 1.15, self.ts, "break"
        )
        self.assertIsNone(
            self.factory.create(signal, [_bar(self.ts)], "CORE")
        )


class ValidatorComponentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)
        self.validator = TradeSetupValidator()

    def _valid(self, **overrides: object) -> TradeSetup:
        payload = {
            "setup_id": "id",
            "symbol": "EURUSD",
            "direction": TradeDirection.LONG,
            "strategy_id": "S",
            "timestamp": self.ts,
            "reason": "r",
            "stop_hint": 1.14,
        }
        payload.update(overrides)
        return TradeSetup(**payload)  # type: ignore[arg-type]

    def test_valid_passes(self) -> None:
        setup = self.validator.validate(self._valid())
        self.assertEqual(setup.setup_id, "id")

    def test_missing_stop_fails(self) -> None:
        with self.assertRaises(TradeSetupValidationError) as ctx:
            self.validator.validate(self._valid(stop_hint=None))
        self.assertIn("stop_hint", str(ctx.exception))

    def test_empty_symbol_fails(self) -> None:
        with self.assertRaises(TradeSetupValidationError) as ctx:
            self.validator.validate(self._valid(symbol="  "))
        self.assertIn("symbol", str(ctx.exception))

    def test_empty_setup_id_fails(self) -> None:
        with self.assertRaises(TradeSetupValidationError):
            self.validator.validate(self._valid(setup_id=""))

    def test_negative_stop_accepted_by_validator_documented_defect(self) -> None:
        """DEF-003: negative stop_hint is not rejected (shallow validator)."""
        setup = self.validator.validate(self._valid(stop_hint=-1.0))
        self.assertEqual(setup.stop_hint, -1.0)


class PolicyAndSizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)
        self.policy = FixedRiskRewardPolicy(r_multiple=2.0, timeout_candles=5)
        self.sizer = FixedRiskSizer()
        self.account = AccountContext(10_000.0, 0.01)

    def _setup(
        self,
        *,
        direction: TradeDirection = TradeDirection.LONG,
        stop: float = 1.14,
        entry: float | None = 1.15,
        target: float | None = None,
        timeout: int | None = None,
    ) -> TradeSetup:
        return TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=direction,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=stop,
            entry_hint=entry,
            target_hint=target,
            timeout_candles=timeout,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
        )

    def test_policy_entry_sl_tp_expiry(self) -> None:
        candles = [_bar(self.ts)]
        result = self.policy.build(self._setup(), candles)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.entry_model, EntryModel.NEXT_CANDLE_OPEN)
        self.assertAlmostEqual(result.entry_price, 1.15)
        self.assertAlmostEqual(result.sl_price, 1.14)
        self.assertAlmostEqual(result.tp_price, 1.17)
        self.assertEqual(result.timeout_candles, 5)

    def test_policy_uses_target_hint(self) -> None:
        result = self.policy.build(
            self._setup(target=1.20), [_bar(self.ts)]
        )
        assert result is not None
        self.assertAlmostEqual(result.tp_price, 1.20)

    def test_policy_missing_entry_hint_uses_close(self) -> None:
        result = self.policy.build(
            self._setup(entry=None), [_bar(self.ts, c=1.151)]
        )
        assert result is not None
        self.assertAlmostEqual(result.entry_price, 1.151)

    def test_policy_zero_stop_distance_rejected(self) -> None:
        self.assertIsNone(
            self.policy.build(self._setup(stop=1.15, entry=1.15), [_bar(self.ts)])
        )

    def test_policy_empty_candles_rejected(self) -> None:
        self.assertIsNone(self.policy.build(self._setup(), []))

    def test_sizer_risk_and_size(self) -> None:
        sized = self.sizer.size(self._setup(), 1.15, 1.14, self.account)
        assert sized is not None
        self.assertAlmostEqual(sized.risk_amount, 100.0)
        self.assertAlmostEqual(sized.position_size, 10_000.0)

    def test_sizer_zero_stop_distance_rejected(self) -> None:
        self.assertIsNone(self.sizer.size(self._setup(), 1.15, 1.15, self.account))

    def test_sizer_non_positive_account_rejected(self) -> None:
        self.assertIsNone(
            self.sizer.size(self._setup(), 1.15, 1.14, AccountContext(0.0, 0.01))
        )
        self.assertIsNone(
            self.sizer.size(self._setup(), 1.15, 1.14, AccountContext(10_000.0, 0.0))
        )


class PlannerOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)
        self.calls: list[str] = []

        class TrackingPolicy(FixedRiskRewardPolicy):
            def build(self_inner, setup, candles):  # noqa: N805
                self.calls.append("policy")
                return super().build(setup, candles)

        class TrackingSizer(FixedRiskSizer):
            def size(self_inner, setup, entry, stop, account):  # noqa: N805
                self.calls.append("sizer")
                return super().size(setup, entry, stop, account)

        self.planner = TradePlanner(
            policy=TrackingPolicy(r_multiple=2.0),
            sizer=TrackingSizer(),
            account=AccountContext(10_000.0, 0.01),
        )

    def test_planner_delegates_and_assembles(self) -> None:
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
            entry_hint=1.15,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
        )
        plan = self.planner.plan(setup, [_bar(self.ts)])
        self.assertEqual(self.calls, ["policy", "sizer"])
        assert plan is not None
        self.assertEqual(plan.status, TradePlanStatus.PLANNED)
        self.assertEqual(plan.planned_at, self.ts)
        self.assertAlmostEqual(plan.sl_price, 1.14)
        self.assertGreater(plan.position_size, 0.0)


class SimulatorLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)

    def _plan(self) -> TradePlan:
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
            entry_hint=1.15,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
        )
        return TradePlan(
            setup=setup,
            entry_model=EntryModel.NEXT_CANDLE_OPEN,
            entry_price=1.15,
            sl_price=1.14,
            tp_price=1.17,
            r_multiple=2.0,
            position_size=1.0,
            risk_amount=100.0,
            timeout_candles=5,
            planned_at=self.ts,
        )

    def test_queue_then_fill_on_open(self) -> None:
        sim = TradeSimulator(max_hold_candles=60)
        sim.add_plan(self._plan())
        self.assertTrue(sim.has_active_lifecycle("S", "EURUSD"))
        # NEXT_CANDLE_OPEN fills on first update after queue
        sim.update(_bar(self.ts, o=1.15, h=1.151, low=1.149, c=1.15))
        self.assertEqual(len(sim.pending_plans.get(("S", "EURUSD"), [])), 0)
        self.assertEqual(len(sim.open_positions.get(("S", "EURUSD"), [])), 1)
        sim.update(
            _bar(self.ts + timedelta(minutes=1), o=1.15, h=1.18, low=1.145, c=1.16)
        )
        trades = sim.get_all_closed_trades()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].close_reason, "TP")

    def test_finalize_without_final_bar_uses_planned_at(self) -> None:
        sim = TradeSimulator()
        sim.add_plan(self._plan())
        sim.finalize_backtest(symbols=["EURUSD"], final_bars={})
        self.assertEqual(len(sim.terminated_setups), 1)
        self.assertEqual(
            sim.terminated_setups[0].termination_time, self.ts
        )
        self.assertEqual(
            sim.terminated_setups[0].reason, "CANCELLED_END_OF_DATA"
        )


class IntegrationPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)

    def test_full_pipeline_closed_trade(self) -> None:
        bars = [
            _bar(self.ts, o=1.15, h=1.151, low=1.14, c=1.15),
            _bar(
                self.ts + timedelta(minutes=15),
                o=1.15,
                h=1.18,
                low=1.145,
                c=1.16,
            ),
        ]
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "qa"
        )
        strategy = MockMapStrategy({self.ts: [signal]})
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)

        self.assertEqual(result.total_signals, 1)
        self.assertEqual(result.accepted_setups_count, 1)
        self.assertEqual(result.rejected_policy_boundary_count, 0)
        self.assertEqual(len(result.closed_trades), 1)
        trade = result.closed_trades[0]
        self.assertEqual(trade.close_reason, "TP")
        self.assertAlmostEqual(trade.pnl_r, 2.0)
        self.assertEqual(result.reconcile_signals()["difference"], 0)
        self.assertEqual(result.reconcile_execution()["difference"], 0)

    def test_duplicate_signals_overlap_ignored(self) -> None:
        bars = [
            _bar(self.ts, o=1.15, h=1.151, low=1.14, c=1.15),
            _bar(
                self.ts + timedelta(minutes=15),
                o=1.15,
                h=1.155,
                low=1.145,
                c=1.15,
            ),
        ]
        sig1 = Signal("EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "a")
        sig2 = Signal(
            "EURUSD",
            SignalType.BULLISH_SWEEP,
            0,
            1.15,
            self.ts + timedelta(minutes=15),
            "b",
        )
        strategy = MockMapStrategy(
            {
                self.ts: [sig1],
                self.ts + timedelta(minutes=15): [sig2],
            }
        )
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        self.assertEqual(result.total_signals, 2)
        self.assertEqual(result.accepted_setups_count, 1)
        self.assertEqual(result.ignored_active_lifecycle_count, 1)

    def test_empty_signal_list_no_crash(self) -> None:
        bars = [_bar(self.ts), _bar(self.ts + timedelta(minutes=15))]
        strategy = MockMapStrategy({})
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        self.assertEqual(result.total_signals, 0)
        self.assertEqual(len(result.closed_trades), 0)

    def test_unsupported_signal_rejected_explicitly(self) -> None:
        bars = [_bar(self.ts), _bar(self.ts + timedelta(minutes=15))]
        signal = Signal(
            "EURUSD", SignalType.CLOSE_OUTSIDE, 1, 1.15, self.ts, "x"
        )
        strategy = MockMapStrategy({self.ts: [signal]})
        result = BacktestRunner().run(strategy, bars, simulate_trades=True)
        self.assertEqual(result.rejected_policy_boundary_count, 1)
        self.assertEqual(result.accepted_setups_count, 0)


class EdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 1, 1, 12, 0, 0)
        self.factory = SweepTradeSetupFactory()
        self.validator = TradeSetupValidator()
        self.planner = TradePlanner(
            FixedRiskRewardPolicy(2.0),
            FixedRiskSizer(),
            AccountContext(10_000.0, 0.01),
        )

    def test_huge_stop_distance_sizes_tiny_position(self) -> None:
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=0.15,
            entry_hint=1.15,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
        )
        setup = self.validator.validate(setup)
        plan = self.planner.plan(setup, [_bar(self.ts)])
        assert plan is not None
        self.assertAlmostEqual(plan.position_size, 100.0)  # 100 / 1.0

    def test_tiny_stop_distance_sizes_huge_position(self) -> None:
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.15 - 1e-6,
            entry_hint=1.15,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
        )
        plan = self.planner.plan(setup, [_bar(self.ts)])
        assert plan is not None
        self.assertGreater(plan.position_size, 1e7)

    def test_pending_timeout_candles_expire_plan(self) -> None:
        """Unfilled plans expire after timeout_candles bars without entry."""
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
            entry_hint=1.15,
            timeout_candles=1,
            entry_model_hint=EntryModel.LIMIT,  # never fills under ConservativeOHLC
        )
        plan = TradePlan(
            setup=setup,
            entry_model=EntryModel.LIMIT,
            entry_price=1.15,
            sl_price=1.14,
            tp_price=1.17,
            r_multiple=2.0,
            position_size=1.0,
            risk_amount=100.0,
            timeout_candles=1,
            planned_at=self.ts,
        )
        sim = TradeSimulator()
        sim.add_plan(plan)
        sim.update(
            _bar(self.ts + timedelta(minutes=1), o=1.15, h=1.151, low=1.149, c=1.15)
        )
        self.assertEqual(sim.get_currently_active_count(), 0)
        self.assertEqual(len(sim.terminated_setups), 1)
        self.assertEqual(sim.terminated_setups[0].reason, "EXPIRED")

    def test_pending_timeout_allows_wait_before_expire(self) -> None:
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
            entry_hint=1.15,
            timeout_candles=3,
            entry_model_hint=EntryModel.LIMIT,
        )
        plan = TradePlan(
            setup=setup,
            entry_model=EntryModel.LIMIT,
            entry_price=1.15,
            sl_price=1.14,
            tp_price=1.17,
            r_multiple=2.0,
            position_size=1.0,
            risk_amount=100.0,
            timeout_candles=3,
            planned_at=self.ts,
        )
        sim = TradeSimulator()
        sim.add_plan(plan)
        sim.update(_bar(self.ts + timedelta(minutes=1)))
        self.assertEqual(sim.get_currently_active_count(), 1)
        sim.update(_bar(self.ts + timedelta(minutes=2)))
        self.assertEqual(sim.get_currently_active_count(), 1)
        sim.update(_bar(self.ts + timedelta(minutes=3)))
        self.assertEqual(sim.get_currently_active_count(), 0)
        self.assertEqual(sim.terminated_setups[0].reason, "EXPIRED")

    def test_malformed_metadata_not_runtime_checked(self) -> None:
        """Soft spot: dataclass typing does not enforce metadata value types at runtime."""
        setup = TradeSetup(
            setup_id="id",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
            metadata={"k": 1},  # type: ignore[dict-item]
        )
        self.assertEqual(setup.metadata["k"], 1)

    def test_calculate_pnl_r_short_and_long(self) -> None:
        self.assertAlmostEqual(
            calculate_pnl_r(TradeDirection.LONG, 1.15, 1.14, 1.17), 2.0
        )
        self.assertAlmostEqual(
            calculate_pnl_r(TradeDirection.SHORT, 1.15, 1.16, 1.13), 2.0
        )


class StrategyRegressionTests(unittest.TestCase):
    def test_liquidity_sweep_signal_shape_unchanged(self) -> None:
        """Strategy still emits Signal; no TradeSetup from strategy itself."""
        strategy = LiquiditySweepStrategy(lookback=2, min_wick_ratio=0.5)
        # Build a minimal bullish sweep window: swing low then reclaim
        base = datetime(2026, 1, 1, 10, 0, 0)
        candles = [
            _bar(base + timedelta(minutes=i), o=1.150, h=1.151, low=1.149, c=1.150)
            for i in range(3)
        ]
        # Prior swing low at index 0, then dig below and close back
        candles.append(
            _bar(
                base + timedelta(minutes=3),
                o=1.149,
                h=1.150,
                low=1.140,
                c=1.148,
            )
        )
        signals = strategy.generate_signals(candles)
        for signal in signals:
            self.assertIsInstance(signal, Signal)
            self.assertIn(
                signal.signal,
                (SignalType.BULLISH_SWEEP, SignalType.BEARISH_SWEEP),
            )


class ReproducibilityTests(unittest.TestCase):
    def test_identical_metrics_across_three_runs(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0)
        bars = [
            _bar(ts, o=1.15, h=1.151, low=1.14, c=1.15),
            _bar(ts + timedelta(minutes=15), o=1.15, h=1.18, low=1.145, c=1.16),
            _bar(ts + timedelta(minutes=30), o=1.16, h=1.161, low=1.155, c=1.158),
        ]
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, ts, "qa"
        )
        strategy_factory = lambda: MockMapStrategy({ts: [signal]})

        digests: list[str] = []
        snapshots: list[dict[str, object]] = []
        for _ in range(3):
            result = BacktestRunner().run(
                strategy_factory(), bars, simulate_trades=True
            )
            snap = {
                "total_signals": result.total_signals,
                "accepted": result.accepted_setups_count,
                "rejected": result.rejected_policy_boundary_count,
                "ignored": result.ignored_active_lifecycle_count,
                "trades": result.total_trades,
                "wins": result.wins,
                "losses": result.losses,
                "win_rate": result.win_rate,
                "expectancy": result.expectancy,
                "profit_factor": result.profit_factor,
                "largest_win": result.largest_win,
                "largest_loss": result.largest_loss,
                "avg_hold": result.avg_holding_duration,
                "trade_fingerprints": tuple(
                    (
                        t.symbol,
                        str(t.direction),
                        t.entry_time.isoformat(),
                        t.exit_time.isoformat(),
                        round(t.entry_price, 10),
                        round(t.exit_price, 10),
                        round(t.pnl_r, 10),
                        t.close_reason,
                    )
                    for t in result.closed_trades
                ),
            }
            snapshots.append(snap)
            digests.append(sha256(repr(snap).encode()).hexdigest())

        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[1], digests[2])
        self.assertEqual(snapshots[0]["trades"], 1)
        self.assertEqual(snapshots[0]["wins"], 1)


class StateMachineContractTests(unittest.TestCase):
    def test_documented_statuses_exist(self) -> None:
        names = {s.value for s in TradePlanStatus}
        self.assertEqual(
            names,
            {"planned", "queued", "active", "closed", "cancelled", "expired"},
        )

    def test_backtest_never_emits_non_planned_status(self) -> None:
        """Evidence: simulator does not mutate TradePlan.status."""
        ts = datetime(2026, 1, 1, 12, 0, 0)
        bars = [
            _bar(ts, o=1.15, h=1.151, low=1.14, c=1.15),
            _bar(ts + timedelta(minutes=15), o=1.15, h=1.18, low=1.145, c=1.16),
        ]
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, ts, "qa"
        )
        # Capture plan status via custom path
        factory = SweepTradeSetupFactory()
        planner = TradePlanner(FixedRiskRewardPolicy(2.0), FixedRiskSizer())
        setup = factory.create(signal, [bars[0]], "QA_MOCK")
        assert setup is not None
        plan = planner.plan(setup, [bars[0]])
        assert plan is not None
        self.assertEqual(plan.status, TradePlanStatus.PLANNED)
        sim = TradeSimulator()
        sim.add_plan(plan)
        sim.update(bars[1])
        # Frozen dataclass: status cannot change without replacing the object
        self.assertEqual(plan.status, TradePlanStatus.PLANNED)


if __name__ == "__main__":
    unittest.main()
