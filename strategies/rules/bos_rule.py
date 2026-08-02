"""Break of Structure (BOS) detection rule."""

from dataclasses import dataclass

from models.bar import Bar


@dataclass(frozen=True)
class BOSResult:
    """Result of Break of Structure detection."""

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


class BOSRule:
    """
    Detects a Break of Structure (BOS).

    Bullish BOS
        Close above previous swing high.

    Bearish BOS
        Close below previous swing low.
    """

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
    ) -> BOSResult:

        if len(candles) < self.lookback + 1:
            return BOSResult(
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

        # -------------------------------------------------
        # Bullish BOS
        # -------------------------------------------------

        if bullish:

            breakout = current.close - swing_high.high

            if breakout > self.min_break_distance:

                strength = min(
                    100,
                    int((breakout + body_size) * 10000),
                )

                return BOSResult(
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
                    reason="Bullish Break of Structure",
                )

        # -------------------------------------------------
        # Bearish BOS
        # -------------------------------------------------

        if bearish:

            breakout = swing_low.low - current.close

            if breakout > self.min_break_distance:

                strength = min(
                    100,
                    int((breakout + body_size) * 10000),
                )

                return BOSResult(
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
                    reason="Bearish Break of Structure",
                )

        return BOSResult(
            detected=False,
            bullish=False,
            bearish=False,
            reason="No Break of Structure",
        )