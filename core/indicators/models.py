"""Typed indicator result models (library-agnostic)."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MACDResult:
    """Moving Average Convergence Divergence components."""

    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


@dataclass(frozen=True)
class BollingerBands:
    """Bollinger Band envelope."""

    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


@dataclass(frozen=True)
class ADXResult:
    """Average Directional Index with directional movement lines."""

    adx: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series
