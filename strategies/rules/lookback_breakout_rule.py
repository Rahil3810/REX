"""Legacy lookback extremum breakout (NOT structural BOS).

Formerly named ``BOSRule``. Retained only for explicit lookback-breakout
semantics and historical tests. Structural BOS lives in
``core.features.generators.bos`` as ``swing_bos_v1``.
"""

from dataclasses import dataclass

from models.bar import Bar


@dataclass(frozen=True)
class LookbackBreakoutResult:
    """Result of a lookback max/min close breakout."""

    detected: bool
    bullish: bool
    bearish: bool

    bos_price: float | None = None
    bos_index: int | None = None

    broken_swing_price: float | None = None
    broken_swing_index: int | None = None

    breakout_distance: float | None = None
    body_size: float | None = None

    candles_since_sweep: int | None = None

    strength: int | None = None

    reason: str = ""


class LookbackBreakoutRule:
    """
    Detects a lookback-window close breakout (not fractal-swing BOS).

    Bullish: close above max high of the prior ``lookback`` candles.
    Bearish: close below min low of the prior ``lookback`` candles.

    Caller must supply ``bullish`` / ``bearish`` direction flags.
    """

    method_id = "lookback_breakout_v1"

    def __init__(
        self,
        lookback: int = 10,
        min_break_distance: float = 0.0,
    ):
        self.lookback = lookback
        self.min_break_distance = min_break_distance

    def detect(
        self,
        candles: list[Bar],
        bullish: bool,
        bearish: bool,
    ) -> LookbackBreakoutResult:

        if len(candles) < self.lookback + 1:
            return LookbackBreakoutResult(
                detected=False,
                bullish=False,
                bearish=False,
                reason="Not enough candles",
            )

        current = candles[-1]
        previous = candles[-self.lookback - 1 : -1]

        swing_high = max(previous, key=lambda c: c.high)
        swing_low = min(previous, key=lambda c: c.low)

        body_size = abs(current.close - current.open)

        if bullish:
            breakout = current.close - swing_high.high
            if breakout > self.min_break_distance:
                strength = min(
                    100,
                    int((breakout + body_size) * 10000),
                )
                return LookbackBreakoutResult(
                    detected=True,
                    bullish=True,
                    bearish=False,
                    bos_price=current.close,
                    bos_index=len(candles) - 1,
                    broken_swing_price=swing_high.high,
                    broken_swing_index=previous.index(swing_high),
                    breakout_distance=breakout,
                    body_size=body_size,
                    strength=strength,
                    reason="Bullish lookback breakout",
                )

        if bearish:
            breakout = swing_low.low - current.close
            if breakout > self.min_break_distance:
                strength = min(
                    100,
                    int((breakout + body_size) * 10000),
                )
                return LookbackBreakoutResult(
                    detected=True,
                    bullish=False,
                    bearish=True,
                    bos_price=current.close,
                    bos_index=len(candles) - 1,
                    broken_swing_price=swing_low.low,
                    broken_swing_index=previous.index(swing_low),
                    breakout_distance=breakout,
                    body_size=body_size,
                    strength=strength,
                    reason="Bearish lookback breakout",
                )

        return LookbackBreakoutResult(
            detected=False,
            bullish=False,
            bearish=False,
            reason="No lookback breakout",
        )
