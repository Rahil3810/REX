"""Market-phase resolution from completed analysis results."""

from core.market_structure_config import MarketPhaseConfig
from models.bar import Bar
from models.market_structure import MarketPhase, MarketTrend


class PhaseAnalyzer:
    """Resolve the market phase without producing trading decisions."""

    def __init__(self, config: MarketPhaseConfig) -> None:
        """Initialize the analyzer.

        Args:
            config: Thresholds and recent-window phase settings.
        """
        self._config = config

    def analyze(
        self,
        trend: MarketTrend,
        trend_strength: int,
        momentum_score: int,
        entry_bars: tuple[Bar, ...],
    ) -> MarketPhase:
        """Resolve the phase from trend, momentum, and recent closes.

        Args:
            trend: Swing-derived market trend.
            trend_strength: Score for structural trend coherence.
            momentum_score: Score for candle-body momentum.
            entry_bars: Completed entry-timeframe candles.

        Returns:
            The current descriptive market phase.
        """
        if momentum_score <= self._config.compression_momentum_score_max:
            return MarketPhase.COMPRESSION
        if trend in {MarketTrend.RANGING, MarketTrend.UNKNOWN}:
            return MarketPhase.RANGE
        if self._is_recent_pullback(trend, entry_bars):
            return MarketPhase.PULLBACK
        if trend_strength >= self._config.strong_trend_score_min:
            return MarketPhase.TREND
        return MarketPhase.REVERSAL

    def _is_recent_pullback(
        self, trend: MarketTrend, bars: tuple[Bar, ...]
    ) -> bool:
        window = self._config.pullback_recent_window
        if len(bars) < window:
            return False
        closes = [bar.close for bar in bars[-window:]]
        if trend == MarketTrend.BULLISH:
            return all(closes[index] < closes[index - 1] for index in range(1, window))
        if trend == MarketTrend.BEARISH:
            return all(closes[index] > closes[index - 1] for index in range(1, window))
        return False
