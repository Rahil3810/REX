"""Unit tests for the indicator subsystem."""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta
from typing import Sequence
from unittest.mock import MagicMock

import pandas as pd

from core.indicators import (
    ADXResult,
    BollingerBands,
    IndicatorEngine,
    MACDResult,
    PandasTAProvider,
)
from models.bar import Bar


def _bars_from_closes(closes: Sequence[float], *, symbol: str = "EURUSD") -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, 12, 0, 0)
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        price = float(close)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=start + timedelta(minutes=index),
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price,
                volume=100.0,
            )
        )
    return tuple(bars)


class PandasTAProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PandasTAProvider()
        self.closes = [float(i) for i in range(1, 51)]
        self.bars = _bars_from_closes(self.closes)

    def test_sma_shape_and_warmup_nans(self) -> None:
        length = 5
        series = self.provider.sma(self.bars, length=length)
        self.assertEqual(len(series), len(self.bars))
        self.assertTrue(series.iloc[: length - 1].isna().all())
        self.assertFalse(math.isnan(series.iloc[length - 1]))

    def test_sma_typical_value(self) -> None:
        series = self.provider.sma(self.bars, length=5)
        # closes 1..5 average to 3.0 at index 4
        self.assertAlmostEqual(float(series.iloc[4]), 3.0)

    def test_ema_shape_and_finite_tail(self) -> None:
        series = self.provider.ema(self.bars, length=10)
        self.assertEqual(len(series), len(self.bars))
        self.assertTrue(math.isfinite(float(series.iloc[-1])))

    def test_rsi_bounds(self) -> None:
        series = self.provider.rsi(self.bars, length=14)
        self.assertEqual(len(series), len(self.bars))
        self.assertTrue(series.isna().any())
        finite = series.dropna()
        self.assertFalse(finite.empty)
        self.assertTrue(((finite >= 0.0) & (finite <= 100.0)).all())

    def test_atr_positive(self) -> None:
        series = self.provider.atr(self.bars, length=14)
        self.assertEqual(len(series), len(self.bars))
        self.assertGreater(float(series.iloc[-1]), 0.0)

    def test_macd_result_shape(self) -> None:
        result = self.provider.macd(self.bars)
        self.assertIsInstance(result, MACDResult)
        self.assertEqual(len(result.macd), len(self.bars))
        self.assertEqual(len(result.signal), len(self.bars))
        self.assertEqual(len(result.histogram), len(self.bars))
        self.assertTrue(math.isfinite(float(result.macd.iloc[-1])))

    def test_bollinger_band_ordering(self) -> None:
        bands = self.provider.bollinger_bands(self.bars, length=20, std=2.0)
        self.assertIsInstance(bands, BollingerBands)
        idx = -1
        self.assertGreater(float(bands.upper.iloc[idx]), float(bands.middle.iloc[idx]))
        self.assertGreater(float(bands.middle.iloc[idx]), float(bands.lower.iloc[idx]))

    def test_adx_result_shape(self) -> None:
        result = self.provider.adx(self.bars, length=14)
        self.assertIsInstance(result, ADXResult)
        self.assertEqual(len(result.adx), len(self.bars))
        self.assertEqual(len(result.plus_di), len(self.bars))
        self.assertEqual(len(result.minus_di), len(self.bars))
        self.assertGreaterEqual(float(result.adx.dropna().iloc[-1]), 0.0)

    def test_insufficient_history_returns_nan_series(self) -> None:
        short = _bars_from_closes([1.0, 2.0, 3.0])
        series = self.provider.sma(short, length=20)
        self.assertEqual(len(series), 3)
        self.assertTrue(series.isna().all())

    def test_empty_bars_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.sma((), length=5)

    def test_invalid_length_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.sma(self.bars, length=0)
        with self.assertRaises(ValueError):
            self.provider.ema(self.bars, length=-1)
        with self.assertRaises(ValueError):
            self.provider.bollinger_bands(self.bars, length=20, std=0)
        with self.assertRaises(ValueError):
            self.provider.macd(self.bars, fast=26, slow=12)


class IndicatorEngineTests(unittest.TestCase):
    def test_engine_delegates_to_provider(self) -> None:
        provider = MagicMock()
        bars = _bars_from_closes([1.0, 2.0, 3.0, 4.0, 5.0])
        expected = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        provider.sma.return_value = expected
        engine = IndicatorEngine(provider)

        result = engine.sma(bars, length=3)

        provider.sma.assert_called_once_with(bars, length=3)
        self.assertIs(result, expected)

    def test_engine_delegates_all_methods(self) -> None:
        provider = MagicMock()
        bars = _bars_from_closes([float(i) for i in range(1, 40)])
        engine = IndicatorEngine(provider)

        engine.ema(bars, length=5)
        engine.rsi(bars, length=7)
        engine.atr(bars, length=7)
        engine.macd(bars, fast=5, slow=10, signal=3)
        engine.bollinger_bands(bars, length=5, std=1.5)
        engine.adx(bars, length=7)

        provider.ema.assert_called_once()
        provider.rsi.assert_called_once()
        provider.atr.assert_called_once()
        provider.macd.assert_called_once()
        provider.bollinger_bands.assert_called_once()
        provider.adx.assert_called_once()

    def test_engine_with_real_provider_matches_provider(self) -> None:
        provider = PandasTAProvider()
        engine = IndicatorEngine(provider)
        bars = _bars_from_closes([float(i) for i in range(1, 40)])
        pd.testing.assert_series_equal(engine.sma(bars, length=5), provider.sma(bars, length=5))
        pd.testing.assert_series_equal(engine.rsi(bars, length=14), provider.rsi(bars, length=14))


class LibraryIsolationTests(unittest.TestCase):
    def test_only_pandas_provider_imports_ta_library(self) -> None:
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        allowed = root / "core" / "indicators" / "pandas_provider.py"
        forbidden_modules = {"pandas_ta", "pandas_ta_classic"}
        offenders: list[str] = []

        for path in root.rglob("*.py"):
            if ".venv" in path.parts or "site-packages" in path.parts:
                continue
            if path.resolve() == allowed.resolve():
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in forbidden_modules:
                            offenders.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in forbidden_modules:
                        offenders.append(f"{path}: from {node.module}")

        self.assertEqual(offenders, [], msg="; ".join(offenders))


if __name__ == "__main__":
    unittest.main()
