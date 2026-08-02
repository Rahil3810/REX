"""IndicatorProvider protocol — calculation backend for IndicatorEngine."""

from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from core.indicators.models import ADXResult, BollingerBands, MACDResult
from models.bar import Bar


class IndicatorProvider(Protocol):
    """
    Computes technical indicators from OHLC bars.

    Implementations may wrap pandas-ta-classic, TA-Lib, NumPy, etc.
    Consumers must depend only on this contract — never on a specific library.
    """

    def sma(self, bars: Sequence[Bar], length: int = 20) -> pd.Series:
        """Simple Moving Average of close."""

    def ema(self, bars: Sequence[Bar], length: int = 20) -> pd.Series:
        """Exponential Moving Average of close."""

    def rsi(self, bars: Sequence[Bar], length: int = 14) -> pd.Series:
        """Relative Strength Index of close."""

    def atr(self, bars: Sequence[Bar], length: int = 14) -> pd.Series:
        """Average True Range."""

    def macd(
        self,
        bars: Sequence[Bar],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> MACDResult:
        """MACD line, signal line, and histogram."""

    def bollinger_bands(
        self,
        bars: Sequence[Bar],
        length: int = 20,
        std: float = 2.0,
    ) -> BollingerBands:
        """Bollinger upper, middle, and lower bands."""

    def adx(self, bars: Sequence[Bar], length: int = 14) -> ADXResult:
        """ADX with +DI and -DI."""
