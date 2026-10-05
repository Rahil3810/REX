"""Unit tests for the indicator subsystem."""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta
from typing import Sequence
from unittest.mock import MagicMock

import pandas as pd

from core.features.config import default_feature_config
from core.features.packs import build_indicator_pack
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


def _bars_from_volumes(
    volumes: Sequence[float | None],
    *,
    symbol: str = "EURUSD",
) -> tuple[Bar, ...]:
    start = datetime(2024, 1, 1, 12, 0, 0)
    bars: list[Bar] = []
    for index, volume in enumerate(volumes):
        price = 1.0 + 0.0001 * index
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=start + timedelta(minutes=index),
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price,
                volume=volume,
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

    def test_rsi_latest_is_deterministic(self) -> None:
        series_a = self.provider.rsi(self.bars, length=14)
        series_b = self.provider.rsi(self.bars, length=14)
        self.assertAlmostEqual(float(series_a.iloc[-1]), float(series_b.iloc[-1]))
        self.assertTrue(math.isfinite(float(series_a.iloc[-1])))

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

    def test_macd_latest_components_are_deterministic(self) -> None:
        first = self.provider.macd(self.bars, fast=12, slow=26, signal=9)
        second = self.provider.macd(self.bars, fast=12, slow=26, signal=9)
        self.assertAlmostEqual(float(first.macd.iloc[-1]), float(second.macd.iloc[-1]))
        self.assertAlmostEqual(float(first.signal.iloc[-1]), float(second.signal.iloc[-1]))
        self.assertAlmostEqual(
            float(first.histogram.iloc[-1]), float(second.histogram.iloc[-1])
        )
        self.assertAlmostEqual(
            float(first.histogram.iloc[-1]),
            float(first.macd.iloc[-1]) - float(first.signal.iloc[-1]),
            places=10,
        )

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

    def test_relative_volume_expected_ratio(self) -> None:
        # 20 bars of volume 10, then current bar volume 20 → 20 / 10 = 2.0
        volumes: list[float | None] = [10.0] * 20 + [20.0]
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertAlmostEqual(float(series.iloc[-1]), 2.0)

    def test_relative_volume_excludes_current_bar_from_baseline(self) -> None:
        # If current were included, mean would be (10*19 + 100)/20 = 14.5 → ~6.9
        # Correct baseline excludes current: mean(10*20)=10 → 100/10 = 10.0
        volumes: list[float | None] = [10.0] * 20 + [100.0]
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertAlmostEqual(float(series.iloc[-1]), 10.0)

    def test_relative_volume_none_when_insufficient_history(self) -> None:
        volumes: list[float | None] = [10.0] * 20  # only 19 previous for last bar
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertTrue(math.isnan(float(series.iloc[-1])))
        self.assertTrue(series.isna().all())

    def test_relative_volume_none_when_volume_missing(self) -> None:
        volumes: list[float | None] = [10.0] * 20 + [None]
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertTrue(math.isnan(float(series.iloc[-1])))

    def test_relative_volume_none_when_baseline_zero(self) -> None:
        volumes: list[float | None] = [0.0] * 20 + [5.0]
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertTrue(math.isnan(float(series.iloc[-1])))

    def test_relative_volume_half_average(self) -> None:
        volumes: list[float | None] = [20.0] * 20 + [10.0]
        bars = _bars_from_volumes(volumes)
        series = self.provider.relative_volume(bars, length=20)
        self.assertAlmostEqual(float(series.iloc[-1]), 0.5)

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
        with self.assertRaises(ValueError):
            self.provider.relative_volume(self.bars, length=0)


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
        engine.relative_volume(bars, length=20)

        provider.ema.assert_called_once()
        provider.rsi.assert_called_once()
        provider.atr.assert_called_once()
        provider.macd.assert_called_once()
        provider.bollinger_bands.assert_called_once()
        provider.adx.assert_called_once()
        provider.relative_volume.assert_called_once_with(bars, length=20)

    def test_engine_with_real_provider_matches_provider(self) -> None:
        provider = PandasTAProvider()
        engine = IndicatorEngine(provider)
        bars = _bars_from_closes([float(i) for i in range(1, 40)])
        pd.testing.assert_series_equal(engine.sma(bars, length=5), provider.sma(bars, length=5))
        pd.testing.assert_series_equal(engine.rsi(bars, length=14), provider.rsi(bars, length=14))
        pd.testing.assert_series_equal(
            engine.relative_volume(bars, length=20),
            provider.relative_volume(bars, length=20),
        )


class IndicatorPackBuilderTests(unittest.TestCase):
    def test_pack_exposes_rsi_macd_and_relative_volume(self) -> None:
        volumes: list[float | None] = [10.0] * 40 + [20.0]
        closes = [float(i) for i in range(1, 42)]
        start = datetime(2024, 1, 1, 12, 0, 0)
        bars = tuple(
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=index),
                open=close,
                high=close + 0.0005,
                low=close - 0.0005,
                close=close,
                volume=volume,
            )
            for index, (close, volume) in enumerate(zip(closes, volumes, strict=True))
        )
        config = default_feature_config()
        engine = IndicatorEngine(PandasTAProvider())
        pack = build_indicator_pack(
            {"M15": bars},
            entry_timeframe="M15",
            config=config,
            indicator_engine=engine,
        )

        expected_rsi = float(engine.rsi(list(bars), length=14).iloc[-1])
        expected_macd = engine.macd(list(bars), fast=12, slow=26, signal=9)
        self.assertAlmostEqual(pack.rsi_last or 0.0, expected_rsi)
        self.assertAlmostEqual(pack.macd_last or 0.0, float(expected_macd.macd.iloc[-1]))
        self.assertAlmostEqual(
            pack.macd_signal_last or 0.0, float(expected_macd.signal.iloc[-1])
        )
        self.assertAlmostEqual(
            pack.macd_histogram_last or 0.0, float(expected_macd.histogram.iloc[-1])
        )
        self.assertAlmostEqual(pack.relative_volume_last or 0.0, 2.0)


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
