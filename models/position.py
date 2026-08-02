"""Position model to represent open positions."""

from dataclasses import dataclass
from datetime import datetime

from models.trade_direction import TradeDirection


@dataclass
class Position:
    """An active, open market position."""

    symbol: str
    direction: TradeDirection
    entry_price: float
    entry_time: datetime
    sl_price: float
    tp_price: float
    max_hold_candles: int
    signal_id: str
    strategy_id: str
    elapsed_candles: int = 0
