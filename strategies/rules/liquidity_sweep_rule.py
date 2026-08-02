"""Liquidity Sweep detection rule."""

from dataclasses import dataclass
from models.bar import Bar


@dataclass(frozen=True)
class LiquiditySweepResult:
    """Result of liquidity sweep detection."""

    # Detection
    detected: bool
    bullish: bool
    bearish: bool

    # Swing information
    swing_price: float | None = None
    swing_index: int | None = None

    # Sweep information
    sweep_price: float | None = None
    candle_index: int | None = None

    # Candle metrics
    wick_size: float | None = None
    body_size: float | None = None
    wick_ratio: float | None = None

    # Context
    candles_since_swing: int | None = None

    # Reserved for future scoring
    confidence: int | None = None

    reason: str = ""


class LiquiditySweepRule:
    """
    Detects liquidity sweeps.

    Bullish Sweep
        Current LOW breaks previous swing LOW
        Candle CLOSES back above swing LOW

    Bearish Sweep
        Current HIGH breaks previous swing HIGH
        Candle CLOSES back below swing HIGH
    """

    def __init__(
        self,
        lookback: int = 10,
        min_wick_ratio: float = 0.60,
        tolerance: float = 0.0,
        require_close_inside: bool = True,
    ):
        self.lookback = lookback
        self.min_wick_ratio = min_wick_ratio
        self.tolerance = tolerance
        self.require_close_inside = require_close_inside

    def detect(self, candles: list[Bar]) -> LiquiditySweepResult:

        if len(candles) < self.lookback + 1:
            return LiquiditySweepResult(
                detected=False,
                bullish=False,
                bearish=False,
                reason="Not enough candles",
            )

        current = candles[-1]
        previous = candles[-self.lookback - 1 : -1]

        # Find swing high and swing low
        swing_high = max(previous, key=lambda c: c.high)
        swing_low = min(previous, key=lambda c: c.low)

        body_size = abs(current.close - current.open)

        upper_wick = current.high - max(current.open, current.close)
        lower_wick = min(current.open, current.close) - current.low

        # -------------------------
        # Bullish Liquidity Sweep
        # -------------------------

        if current.low < (swing_low.low - self.tolerance):

            closes_inside = (
                current.close > swing_low.low
                if self.require_close_inside
                else True
            )

            wick_ratio = (
                lower_wick / (body_size + lower_wick)
                if (body_size + lower_wick) > 0
                else 0
            )

            if closes_inside and wick_ratio >= self.min_wick_ratio:

                return LiquiditySweepResult(
                    detected=True,
                    bullish=True,
                    bearish=False,
                    swing_price=swing_low.low,
                    swing_index=previous.index(swing_low),
                    sweep_price=current.low,
                    candle_index=len(candles) - 1,
                    wick_size=lower_wick,
                    body_size=body_size,
                    wick_ratio=round(wick_ratio, 2),
                    candles_since_swing=self.lookback,
                    confidence=None,
                    reason="Bullish liquidity sweep",
                )

        # -------------------------
        # Bearish Liquidity Sweep
        # -------------------------

        if current.high > (swing_high.high + self.tolerance):

            closes_inside = (
                current.close < swing_high.high
                if self.require_close_inside
                else True
            )

            wick_ratio = (
                upper_wick / (body_size + upper_wick)
                if (body_size + upper_wick) > 0
                else 0
            )

            if closes_inside and wick_ratio >= self.min_wick_ratio:

                return LiquiditySweepResult(
                    detected=True,
                    bullish=False,
                    bearish=True,
                    swing_price=swing_high.high,
                    swing_index=previous.index(swing_high),
                    sweep_price=current.high,
                    candle_index=len(candles) - 1,
                    wick_size=upper_wick,
                    body_size=body_size,
                    wick_ratio=round(wick_ratio, 2),
                    candles_since_swing=self.lookback,
                    confidence=None,
                    reason="Bearish liquidity sweep",
                )

        return LiquiditySweepResult(
            detected=False,
            bullish=False,
            bearish=False,
            reason="No liquidity sweep detected",
        )