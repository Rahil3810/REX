"""TradeSetupFactory: Signal → TradeSetup (opportunity)."""

from collections.abc import Sequence
from typing import Protocol

from models.bar import Bar
from models.entry_model import EntryModel
from models.signal import Signal, SignalType
from models.trade_direction import TradeDirection
from models.trade_setup import TradeSetup


class TradeSetupFactory(Protocol):
    """Convert a detection Signal into an execution-agnostic TradeSetup."""

    def create(
        self,
        signal: Signal,
        candles: Sequence[Bar],
        strategy_id: str,
    ) -> TradeSetup | None:
        """Return a TradeSetup, or None when this factory does not handle the signal."""
        ...


class SweepTradeSetupFactory:
    """Build TradeSetup opportunities from liquidity-sweep signals."""

    def create(
        self,
        signal: Signal,
        candles: Sequence[Bar],
        strategy_id: str,
    ) -> TradeSetup | None:
        if signal.signal not in (SignalType.BULLISH_SWEEP, SignalType.BEARISH_SWEEP):
            return None
        if not candles:
            return None

        current_bar = candles[-1]
        if signal.signal == SignalType.BULLISH_SWEEP:
            direction = TradeDirection.LONG
            stop_hint = current_bar.low
        else:
            direction = TradeDirection.SHORT
            stop_hint = current_bar.high

        setup_id = (
            f"{signal.symbol}_{signal.timestamp.isoformat()}_{signal.signal.value}"
        )
        return TradeSetup(
            setup_id=setup_id,
            symbol=signal.symbol,
            direction=direction,
            strategy_id=strategy_id,
            timestamp=signal.timestamp,
            reason=signal.reason,
            entry_hint=signal.price,
            stop_hint=stop_hint,
            target_hint=None,
            entry_model_hint=EntryModel.NEXT_CANDLE_OPEN,
            metadata={"signal_type": signal.signal.value},
        )
