"""Domain model for trade setups that expired or were cancelled."""

from dataclasses import dataclass
from datetime import datetime

from models.trade_direction import TradeDirection


@dataclass(frozen=True)
class TerminatedSetup:
    """Record of a trade setup that expired or was cancelled without entering."""

    symbol: str
    direction: TradeDirection
    strategy_id: str
    timestamp: datetime  # Setup creation timestamp
    termination_time: datetime
    reason: str  # "EXPIRED" | "CANCELLED_END_OF_DATA" | "REJECTED_INVALID_ENTRY"
    signal_id: str
