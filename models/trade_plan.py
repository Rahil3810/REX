"""TradePlan: executable trade produced by the planning layer."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from models.entry_model import EntryModel
from models.trade_direction import TradeDirection
from models.trade_setup import TradeSetup


class TradePlanStatus(StrEnum):
    """
    Lifecycle states for a trade plan.

    Only PLANNED is used by the backtest path today. QUEUED/ACTIVE/CLOSED/
    CANCELLED/EXPIRED establish the future paper/live lifecycle surface.
    """

    PLANNED = "planned"
    QUEUED = "queued"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class TradePlan:
    """
    Executable trade consumed by backtest (and future paper/live) executors.

    estimated_fees / estimated_spread / estimated_slippage default to 0.0 and
    are not applied by the current OHLC fill model — they reserve the contract
    for realistic cost modeling later.

    planned_at is when this plan was produced (causal bar time in backtests).
    Execution timestamps belong on future executor lifecycle updates, not here.
    """

    setup: TradeSetup
    entry_model: EntryModel
    entry_price: float
    sl_price: float
    tp_price: float
    r_multiple: float
    position_size: float
    risk_amount: float
    timeout_candles: int
    planned_at: datetime
    status: TradePlanStatus = TradePlanStatus.PLANNED
    estimated_fees: float = 0.0
    estimated_spread: float = 0.0
    estimated_slippage: float = 0.0
    planner_metadata: dict[str, str] = field(default_factory=dict)

    @property
    def symbol(self) -> str:
        return self.setup.symbol

    @property
    def direction(self) -> TradeDirection:
        return self.setup.direction

    @property
    def strategy_id(self) -> str:
        return self.setup.strategy_id

    @property
    def setup_id(self) -> str:
        return self.setup.setup_id

    @property
    def timestamp(self) -> datetime:
        return self.setup.timestamp
