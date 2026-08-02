"""Candle-body momentum analysis."""

from collections.abc import Sequence

from core.market_structure_config import MomentumConfig
from models.bar import Bar
from models.market_structure import MomentumState


class MomentumAnalyzer:
    """Compare recent candle bodies with their historical average."""

    def __init__(self, config: MomentumConfig) -> None:
        """Initialize the analyzer.

        Args:
            config: Momentum windows and classification ratios.
        """
        self._config = config

    def analyze(self, bars: tuple[Bar, ...]) -> tuple[MomentumState, str]:
        """Classify body-size momentum.

        Args:
            bars: Completed candles in chronological order.

        Returns:
            The momentum state and its human-readable explanation.
        """
        if len(bars) < self._config.historical_window:
            return (
                MomentumState.NORMAL,
                "Not enough completed candles for configured momentum window; "
                "classified as normal momentum.",
            )

        historical_bars = bars[-self._config.historical_window :]
        recent_bars = bars[-self._config.recent_window :]
        historical_average = self._average_body_size(historical_bars)
        recent_average = self._average_body_size(recent_bars)
        if historical_average == 0:
            return (
                MomentumState.LOW,
                "Historical candle body average is zero; classified as low momentum.",
            )

        ratio = recent_average / historical_average
        if ratio < self._config.low_ratio:
            state = MomentumState.LOW
        elif ratio > self._config.high_ratio:
            state = MomentumState.HIGH
        else:
            state = MomentumState.NORMAL
        return (
            state,
            f"Recent average candle body {recent_average:.5f} versus "
            f"historical average {historical_average:.5f}; ratio {ratio:.2f}.",
        )

    @staticmethod
    def _average_body_size(bars: Sequence[Bar]) -> float:
        return sum(abs(bar.close - bar.open) for bar in bars) / len(bars)
