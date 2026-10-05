"""Reusable indicator engine — delegates all math to an IndicatorProvider."""

from collections.abc import Sequence

import pandas as pd

from core.indicators.indicator_provider import IndicatorProvider
from core.indicators.models import ADXResult, BollingerBands, MACDResult
from models.bar import Bar


class IndicatorEngine:
    """
    Single REX API for technical indicators.

    Contains no indicator mathematics. Swap providers (pandas-ta-classic,
    TA-Lib, NumPy, …) without changing callers.
    """

    def __init__(self, provider: IndicatorProvider) -> None:
        self._provider = provider

    @property
    def provider(self) -> IndicatorProvider:
        return self._provider

    def sma(self, bars: Sequence[Bar], length: int = 20) -> pd.Series:
        return self._provider.sma(bars, length=length)

    def ema(self, bars: Sequence[Bar], length: int = 20) -> pd.Series:
        return self._provider.ema(bars, length=length)

    def rsi(self, bars: Sequence[Bar], length: int = 14) -> pd.Series:
        return self._provider.rsi(bars, length=length)

    def atr(self, bars: Sequence[Bar], length: int = 14) -> pd.Series:
        return self._provider.atr(bars, length=length)

    def macd(
        self,
        bars: Sequence[Bar],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> MACDResult:
        return self._provider.macd(bars, fast=fast, slow=slow, signal=signal)

    def bollinger_bands(
        self,
        bars: Sequence[Bar],
        length: int = 20,
        std: float = 2.0,
    ) -> BollingerBands:
        return self._provider.bollinger_bands(bars, length=length, std=std)

    def adx(self, bars: Sequence[Bar], length: int = 14) -> ADXResult:
        return self._provider.adx(bars, length=length)

    def relative_volume(self, bars: Sequence[Bar], length: int = 20) -> pd.Series:
        return self._provider.relative_volume(bars, length=length)
