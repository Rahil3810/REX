"""Closed trade model representing realized trade results."""

from dataclasses import dataclass
from datetime import datetime

from models.trade_direction import TradeDirection


@dataclass(frozen=True)
class ClosedTrade:
    """An immutable record of a completed trade."""

    symbol: str
    direction: TradeDirection
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    sl_price: float
    tp_price: float
    pnl_r: float  # Profit or loss in risk units (R-multiples)
    close_reason: str  # "SL" | "TP" | "TIMEOUT" | "AMBIGUITY" | "FORCE_CLOSE_END_OF_DATA"
    holding_duration_candles: int
    signal_id: str
    strategy_id: str
