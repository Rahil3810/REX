"""Tests for provider-neutral historical reads."""

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from historical.config import load_historical_config
from historical.exceptions import UnsupportedHistoricalDataError
from historical.provider import HistoricalDataProvider
from historical.storage import HistoricalStorage
from models.bar import Bar


class HistoricalProviderTests(unittest.TestCase):
    def test_filters_year_files_to_inclusive_requested_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(load_historical_config(), data_directory=Path(directory))
            storage = HistoricalStorage(config.data_directory)
            storage.write_year(
                "EURUSD", "M1", 2024,
                [
                    Bar("EURUSD", datetime(2024, 1, 1), 1, 2, 0.5, 1.5),
                    Bar("EURUSD", datetime(2024, 2, 1), 2, 3, 1.5, 2.5),
                ],
                date(2024, 1, 1), date(2024, 12, 31),
            )
            bars = HistoricalDataProvider(config, storage=storage).get_bars(
                "EURUSD", "M1", date(2024, 2, 1), date(2024, 2, 1)
            )
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].timestamp.month, 2)

    def test_rejects_unconfigured_symbol_and_future_timeframe(self) -> None:
        provider = HistoricalDataProvider(load_historical_config())
        with self.assertRaises(UnsupportedHistoricalDataError):
            provider.get_bars("USDJPY", "M1", date(2024, 1, 1), date(2024, 1, 2))
        with self.assertRaises(UnsupportedHistoricalDataError):
            provider.get_bars("EURUSD", "H1", date(2024, 1, 1), date(2024, 1, 2))
