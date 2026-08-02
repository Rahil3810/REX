"""Tests for historical-data configuration."""

import json
import tempfile
import unittest
from pathlib import Path

from historical.config import load_historical_config
from historical.exceptions import HistoricalConfigurationError


class HistoricalConfigTests(unittest.TestCase):
    def test_loads_typed_configuration(self) -> None:
        payload = {
            "provider": "dukascopy",
            "symbols": ["EURUSD"],
            "timeframe": "M1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "timeout_seconds": 30,
            "retries": 2,
            "retry_delay_seconds": 0.5,
            "data_directory": "data/historical",
            "overwrite_existing_files": False,
            "duka_threads": 3,
            "include_header": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_historical_config(path)
        self.assertEqual(config.symbols, ("EURUSD",))
        self.assertEqual(config.start_date.year, 2024)
        self.assertEqual(config.duka_threads, 3)

    def test_rejects_invalid_range_and_timeframe(self) -> None:
        payload = {
            "provider": "dukascopy", "symbols": ["EURUSD"], "timeframe": "H1",
            "start_date": "2025-01-01", "end_date": "2024-01-01",
            "timeout_seconds": 30, "retries": 1, "retry_delay_seconds": 0,
            "data_directory": "data", "overwrite_existing_files": False,
            "duka_threads": 1, "include_header": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(HistoricalConfigurationError):
                load_historical_config(path)
