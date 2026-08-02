"""Liquidity Sweep strategy implementation."""

from collections.abc import Sequence
from datetime import datetime

from models.bar import Bar
from models.signal import Signal, SignalType
from strategies.base_strategy import BaseStrategy
from strategies.rules.liquidity_sweep_rule import LiquiditySweepRule


class LiquiditySweepStrategy(BaseStrategy):
    """
    Orchestrates LiquiditySweepRule to detect sweeps and emit signals.
    """

    strategy_id = "S008"
    strategy_name = "Liquidity Sweep V1"
    description = "Orchestrates LiquiditySweepRule to detect bullish/bearish sweeps."

    def __init__(
        self,
        lookback: int = 10,
        min_wick_ratio: float = 0.60,
        tolerance: float = 0.0,
        require_close_inside: bool = True,
    ) -> None:
        self.lookback = lookback
        self.min_wick_ratio = min_wick_ratio
        self.tolerance = tolerance
        self.require_close_inside = require_close_inside
        
        self.rule = LiquiditySweepRule(
            lookback=lookback,
            min_wick_ratio=min_wick_ratio,
            tolerance=tolerance,
            require_close_inside=require_close_inside,
        )
        
        # Track the last timestamp we emitted a signal for, per symbol, to prevent duplicate signals
        self._last_signal_timestamps: dict[str, datetime] = {}

    def reset(self) -> None:
        """Reset duplicate signal timestamps."""
        self._last_signal_timestamps.clear()

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        """
        Evaluate candle history for bullish or bearish sweeps.
        """
        if not candles:
            return []

        current_bar = candles[-1]
        
        # Prevent emitting duplicate signals on the same candle
        if self._last_signal_timestamps.get(current_bar.symbol) == current_bar.timestamp:
            return []

        # Extract only the minimum bounded candle window required by the rule
        required_length = self.lookback + 1
        window = list(candles[-required_length:]) if len(candles) > required_length else list(candles)

        result = self.rule.detect(window)
        if not result.detected:
            return []

        signal_type = (
            SignalType.BULLISH_SWEEP
            if result.bullish
            else SignalType.BEARISH_SWEEP
        )

        self._last_signal_timestamps[current_bar.symbol] = current_bar.timestamp

        return [
            Signal(
                symbol=current_bar.symbol,
                signal=signal_type,
                zone_id=0,  # Price action strategy without zone requirements
                price=current_bar.close,
                timestamp=current_bar.timestamp,
                reason=result.reason,
            )
        ]
