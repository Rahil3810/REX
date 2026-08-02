"""Unit tests for the shared execution layer."""

import unittest
from datetime import datetime

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
from models.trade_plan import TradePlanStatus
from models.trade_setup import TradeSetup


def _bar(ts: datetime, low: float = 1.14, high: float = 1.16, close: float = 1.15) -> Bar:
    return Bar("EURUSD", ts, close, high, low, close)


class ExecutionLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ts = datetime(2026, 6, 20, 12, 0, 0)
        self.factory = SweepTradeSetupFactory()
        self.validator = TradeSetupValidator()
        self.planner = TradePlanner(
            policy=FixedRiskRewardPolicy(r_multiple=2.0),
            sizer=FixedRiskSizer(),
            account=AccountContext(equity=10_000.0, risk_fraction=0.01),
        )

    def test_sweep_factory_builds_long_setup(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "sweep"
        )
        candles = [_bar(self.ts, low=1.14, high=1.16)]
        setup = self.factory.create(signal, candles, "S008")
        self.assertIsNotNone(setup)
        assert setup is not None
        self.assertEqual(setup.direction, TradeDirection.LONG)
        self.assertAlmostEqual(setup.stop_hint or 0.0, 1.14)
        self.assertEqual(setup.entry_model_hint, EntryModel.NEXT_CANDLE_OPEN)

    def test_factory_rejects_breakout_signal(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BREAK_ABOVE, 1, 1.15, self.ts, "break"
        )
        setup = self.factory.create(signal, [_bar(self.ts)], "CORE")
        self.assertIsNone(setup)

    def test_validator_requires_stop_hint(self) -> None:
        setup = TradeSetup(
            setup_id="x",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=None,
        )
        with self.assertRaises(TradeSetupValidationError):
            self.validator.validate(setup)

    def test_planner_produces_planned_trade_plan(self) -> None:
        signal = Signal(
            "EURUSD", SignalType.BULLISH_SWEEP, 0, 1.15, self.ts, "sweep"
        )
        candles = [_bar(self.ts, low=1.14, high=1.16, close=1.15)]
        setup = self.factory.create(signal, candles, "S008")
        assert setup is not None
        setup = self.validator.validate(setup)
        plan = self.planner.plan(setup, candles)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.status, TradePlanStatus.PLANNED)
        self.assertEqual(plan.planned_at, self.ts)
        self.assertAlmostEqual(plan.sl_price, 1.14)
        self.assertAlmostEqual(plan.r_multiple, 2.0)
        self.assertGreater(plan.position_size, 0.0)
        self.assertAlmostEqual(plan.risk_amount, 100.0)
        self.assertEqual(plan.estimated_fees, 0.0)

    def test_fixed_risk_sizer(self) -> None:
        setup = TradeSetup(
            setup_id="x",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            strategy_id="S",
            timestamp=self.ts,
            reason="r",
            stop_hint=1.14,
        )
        sized = FixedRiskSizer().size(
            setup, 1.15, 1.14, AccountContext(10_000.0, 0.01)
        )
        self.assertIsNotNone(sized)
        assert sized is not None
        self.assertAlmostEqual(sized.risk_amount, 100.0)
        self.assertAlmostEqual(sized.position_size, 100.0 / 0.01)


if __name__ == "__main__":
    unittest.main()
