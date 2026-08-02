"""Retest detection rule."""

from dataclasses import dataclass

from models.bar import Bar


@dataclass(frozen=True)
class RetestResult:
    """Result of a BOS retest."""

    detected: bool
    bullish: bool
    bearish: bool

    retest_price: float | None = None
    retest_index: int | None = None

    rejection_size: float | None = None
    wick_size: float | None = None

    candles_since_bos: int | None = None

    strength: int | None = None

    reason: str = ""


class RetestRule:
    """
    Detect whether price retests a Break of Structure level and rejects it.
    """

    def __init__(
        self,
        tolerance: float = 0.0005,
        max_wait: int = 5,
    ):
        self.tolerance = tolerance
        self.max_wait = max_wait

    def detect(
        self,
        candles: list[Bar],
        bos_price: float,
        bullish: bool,
        bearish: bool,
    ) -> RetestResult:

        if len(candles) < 2:
            return RetestResult(
                detected=False,
                bullish=False,
                bearish=False,
                reason="Not enough candles",
            )

        current = candles[-1]

        # -------------------------
        # Bullish Retest
        # -------------------------

        if bullish:

            touched = current.low <= bos_price + self.tolerance

            rejected = current.close > bos_price

            if touched and rejected:

                wick = min(current.open, current.close) - current.low
                rejection = current.close - bos_price

                strength = min(
                    100,
                    int((wick + rejection) * 10000),
                )

                return RetestResult(
                    detected=True,
                    bullish=True,
                    bearish=False,
                    retest_price=current.close,
                    retest_index=len(candles) - 1,
                    rejection_size=rejection,
                    wick_size=wick,
                    strength=strength,
                    reason="Bullish BOS Retest",
                )

        # -------------------------
        # Bearish Retest
        # -------------------------

        if bearish:

            touched = current.high >= bos_price - self.tolerance

            rejected = current.close < bos_price

            if touched and rejected:

                wick = current.high - max(current.open, current.close)
                rejection = bos_price - current.close

                strength = min(
                    100,
                    int((wick + rejection) * 10000),
                )

                return RetestResult(
                    detected=True,
                    bullish=False,
                    bearish=True,
                    retest_price=current.close,
                    retest_index=len(candles) - 1,
                    rejection_size=rejection,
                    wick_size=wick,
                    strength=strength,
                    reason="Bearish BOS Retest",
                )

        return RetestResult(
            detected=False,
            bullish=False,
            bearish=False,
            reason="No valid retest",
        )