"""TradePlanner: orchestrate ExecutionPolicy + PositionSizer → TradePlan."""

from collections.abc import Sequence

from execution.policies import ExecutionPolicy
from execution.sizers import PositionSizer
from models.account_context import AccountContext
from models.bar import Bar
from models.trade_plan import TradePlan, TradePlanStatus
from models.trade_setup import TradeSetup


class TradePlanner:
    """
    Thin orchestrator: valid TradeSetup → TradePlan.

    Assumes TradeSetup already passed TradeSetupValidator.
    Business rules live in ExecutionPolicy and PositionSizer, not here.
    """

    def __init__(
        self,
        policy: ExecutionPolicy,
        sizer: PositionSizer,
        account: AccountContext | None = None,
    ) -> None:
        self.policy = policy
        self.sizer = sizer
        self.account = account if account is not None else AccountContext()

    def plan(
        self,
        setup: TradeSetup,
        candles: Sequence[Bar],
    ) -> TradePlan | None:
        """Build an executable TradePlan, or None if policy/sizer cannot proceed."""
        priced = self.policy.build(setup, candles)
        if priced is None:
            return None

        sized = self.sizer.size(
            setup,
            priced.entry_price,
            priced.sl_price,
            self.account,
        )
        if sized is None:
            return None

        planned_at = candles[-1].timestamp if candles else setup.timestamp

        return TradePlan(
            setup=setup,
            entry_model=priced.entry_model,
            entry_price=priced.entry_price,
            sl_price=priced.sl_price,
            tp_price=priced.tp_price,
            r_multiple=priced.r_multiple,
            position_size=sized.position_size,
            risk_amount=sized.risk_amount,
            timeout_candles=priced.timeout_candles,
            planned_at=planned_at,
            status=TradePlanStatus.PLANNED,
            estimated_fees=0.0,
            estimated_spread=0.0,
            estimated_slippage=0.0,
            planner_metadata={
                "policy": type(self.policy).__name__,
                "sizer": type(self.sizer).__name__,
            },
        )
