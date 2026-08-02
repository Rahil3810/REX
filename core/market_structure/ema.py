"""EMA confirmation analysis for swing-derived trends."""

from collections.abc import Sequence
from enum import StrEnum

from core.market_structure_config import EmaConfig
from models.bar import Bar
from models.market_structure import MarketTrend


class EmaAlignmentStatus(StrEnum):
    """Possible EMA confirmation states."""

    ALIGNED = "aligned"
    PARTIAL = "partial"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EmaAnalyzer:
    """Evaluate EMA alignment as supporting trend evidence only."""

    def __init__(self, config: EmaConfig) -> None:
        """Initialize the analyzer.

        Args:
            config: Fast and slow EMA periods.
        """
        self._config = config

    def analyze(
        self,
        trend: MarketTrend,
        entry_timeframe: str,
        higher_timeframes: tuple[str, ...],
        bars_by_timeframe: dict[str, tuple[Bar, ...]],
    ) -> tuple[EmaAlignmentStatus, str]:
        """Evaluate EMA confirmation across configured timeframes.

        Args:
            trend: Swing-derived entry-timeframe trend.
            entry_timeframe: Primary analysis timeframe.
            higher_timeframes: Configured confirmation timeframes.
            bars_by_timeframe: Normalized completed candles by timeframe.

        Returns:
            The alignment status and its explanation.
        """
        if trend in {MarketTrend.RANGING, MarketTrend.UNKNOWN}:
            return (
                EmaAlignmentStatus.NEUTRAL,
                "EMA alignment treated as neutral because swing structure is not directional.",
            )

        timeframes = (entry_timeframe,) + higher_timeframes
        available: list[str] = []
        aligned: list[str] = []
        missing: list[str] = []
        for timeframe in timeframes:
            bars = bars_by_timeframe.get(timeframe)
            if not bars:
                missing.append(timeframe)
                continue
            ema_fast = self._ema([bar.close for bar in bars], self._config.fast_period)
            ema_slow = self._ema([bar.close for bar in bars], self._config.slow_period)
            if ema_fast is None or ema_slow is None:
                missing.append(timeframe)
                continue
            available.append(timeframe)
            if trend == MarketTrend.BULLISH and ema_fast > ema_slow:
                aligned.append(timeframe)
            if trend == MarketTrend.BEARISH and ema_fast < ema_slow:
                aligned.append(timeframe)

        if not available:
            return (
                EmaAlignmentStatus.UNKNOWN,
                "Not enough completed candles to calculate configured EMA periods.",
            )
        if len(aligned) == len(available) and not missing:
            relation = "above" if trend == MarketTrend.BULLISH else "below"
            return (
                EmaAlignmentStatus.ALIGNED,
                f"EMA{self._config.fast_period} is {relation} "
                f"EMA{self._config.slow_period} on all configured "
                f"timeframes: {', '.join(aligned)}.",
            )
        if aligned:
            reason = f"EMA alignment confirms swing trend on: {', '.join(aligned)}."
            if missing:
                reason += f" Missing EMA data: {', '.join(missing)}."
            return EmaAlignmentStatus.PARTIAL, reason

        reason = (
            "EMA alignment does not confirm the swing trend on available "
            f"timeframes: {', '.join(available)}."
        )
        if missing:
            reason += f" Missing EMA data: {', '.join(missing)}."
        return EmaAlignmentStatus.NEUTRAL, reason

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float | None:
        if len(values) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema
        return ema
