"""OHLC bar representation used by data feeds and strategies."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    """A single price bar (candle) for a trading symbol."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
