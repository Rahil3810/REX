"""Tests for strict historical CSV parsing."""

import tempfile
import unittest
from pathlib import Path

from historical.exceptions import HistoricalParseError
from historical.parser import HistoricalDataParser


class HistoricalParserTests(unittest.TestCase):
    def test_parses_duka_column_order_into_bars(self) -> None:
        content = (
            "time,open,close,high,low\n"
            "2024-01-02 00:00:00.000000,1.10,1.11,1.12,1.09\n"
            "2024-01-02 00:01:00.000000,1.11,1.12,1.13,1.10\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duka.csv"
            path.write_text(content, encoding="utf-8")
            bars = HistoricalDataParser().parse_file(path, "EURUSD")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].symbol, "EURUSD")
        self.assertEqual(bars[0].high, 1.12)
        self.assertEqual(bars[1].timestamp.minute, 1)

    def test_rejects_duplicates_missing_values_and_invalid_ohlc(self) -> None:
        invalid_files = (
            "timestamp,open,high,low,close\n2024-01-01 00:00:00,1,2,0.5,1\n2024-01-01 00:00:00,1,2,0.5,1\n",
            "timestamp,open,high,low,close\n2024-01-01 00:00:00,,2,0.5,1\n",
            "timestamp,open,high,low,close\n2024-01-01 00:00:00,1,0.5,2,1\n",
        )
        for content in invalid_files:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.csv"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(HistoricalParseError):
                    HistoricalDataParser().parse_file(path, "EURUSD")
