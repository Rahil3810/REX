"""TradeSetup: execution-agnostic trading opportunity."""

from dataclasses import dataclass, field
from datetime import datetime

from models.entry_model import EntryModel
from models.trade_direction import TradeDirection


@dataclass(frozen=True)
class TradeSetup:
    """
    A trading opportunity produced from strategy detection.

    Contains only opportunity facts and structural hints. Must not include
    position size, account risk, margin, fees, or execution state.
    """

    setup_id: str
    symbol: str
    direction: TradeDirection
    strategy_id: str
    timestamp: datetime
    reason: str
    timeframe: str | None = None
    confidence: float | None = None
    timeout_candles: int | None = None
    entry_hint: float | None = None
    stop_hint: float | None = None
    target_hint: float | None = None
    entry_model_hint: EntryModel | None = None
    metadata: dict[str, str] = field(default_factory=dict)
