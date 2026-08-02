"""Swing-based trend analysis for completed candles."""

from core.market_structure.context import StructureSnapshot
from core.market_structure_config import SwingDetectionConfig
from models.bar import Bar
from models.market_structure import MarketTrend


class TrendAnalyzer:
    """Classify trend from strict local swing highs and swing lows."""

    def __init__(self, config: SwingDetectionConfig) -> None:
        """Initialize the analyzer.

        Args:
            config: Swing-window and minimum-swing settings.
        """
        self._config = config

    def analyze(self, timeframe: str, bars: tuple[Bar, ...]) -> StructureSnapshot:
        """Analyze completed candles for one timeframe.

        Args:
            timeframe: Timeframe represented by the candles.
            bars: Completed candles in chronological order.

        Returns:
            A snapshot containing detected swings, trend, and explanation.
        """
        swing_highs, swing_lows = self._find_swings(bars)
        required = self._config.minimum_swings
        if len(swing_highs) < required or len(swing_lows) < required:
            return StructureSnapshot(
                timeframe=timeframe,
                trend=MarketTrend.UNKNOWN,
                reason=(
                    f"Insufficient completed swing points on {timeframe}: "
                    f"{len(swing_highs)} highs and {len(swing_lows)} lows found."
                ),
                swing_highs=swing_highs,
                swing_lows=swing_lows,
            )

        recent_highs = swing_highs[-required:]
        recent_lows = swing_lows[-required:]
        highs_rising = all(
            recent_highs[index] > recent_highs[index - 1]
            for index in range(1, len(recent_highs))
        )
        lows_rising = all(
            recent_lows[index] > recent_lows[index - 1]
            for index in range(1, len(recent_lows))
        )
        highs_falling = all(
            recent_highs[index] < recent_highs[index - 1]
            for index in range(1, len(recent_highs))
        )
        lows_falling = all(
            recent_lows[index] < recent_lows[index - 1]
            for index in range(1, len(recent_lows))
        )

        if highs_rising and lows_rising:
            trend = MarketTrend.BULLISH
            reason = (
                f"Detected consecutive higher highs {recent_highs} and "
                f"higher lows {recent_lows} on {timeframe}."
            )
        elif highs_falling and lows_falling:
            trend = MarketTrend.BEARISH
            reason = (
                f"Detected consecutive lower highs {recent_highs} and "
                f"lower lows {recent_lows} on {timeframe}."
            )
        else:
            trend = MarketTrend.RANGING
            reason = (
                f"Swing highs {recent_highs} and swing lows {recent_lows} "
                f"do not form a clean directional structure on {timeframe}."
            )

        return StructureSnapshot(
            timeframe=timeframe,
            trend=trend,
            reason=reason,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
        )

    def _find_swings(
        self, bars: tuple[Bar, ...]
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        left = self._config.left_bars
        right = self._config.right_bars
        swing_highs: list[float] = []
        swing_lows: list[float] = []
        if len(bars) < left + right + 1:
            return (), ()

        for index in range(left, len(bars) - right):
            candidate = bars[index]
            left_window = bars[index - left : index]
            right_window = bars[index + 1 : index + right + 1]
            if all(candidate.high > bar.high for bar in left_window + right_window):
                swing_highs.append(candidate.high)
            if all(candidate.low < bar.low for bar in left_window + right_window):
                swing_lows.append(candidate.low)
        return tuple(swing_highs), tuple(swing_lows)
