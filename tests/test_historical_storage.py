"""Tests for yearly historical storage."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from historical.parser import HistoricalDataParser
from historical.storage import HistoricalStorage
from models.bar import Bar


class HistoricalStorageTests(unittest.TestCase):
    def test_writes_canonical_year_partition_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            path = storage.write_year(
                "eurusd", "m1", 2024,
                [Bar("EURUSD", datetime(2024, 1, 2), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1), date(2024, 12, 31),
            )
            self.assertEqual(path, Path(directory) / "EURUSD" / "M1" / "2024.csv")
            self.assertTrue(storage.has_coverage(
                "EURUSD", "M1", date(2024, 2, 1), date(2024, 3, 1)
            ))
            self.assertEqual(len(HistoricalDataParser().parse_file(path, "EURUSD")), 1)

    def test_lists_only_existing_years_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            for year in (2023, 2025):
                storage.write_year("EURUSD", "M1", year, [], date(year, 1, 1), date(year, 12, 31))
            self.assertEqual(
                [path.name for path in storage.existing_files("EURUSD", "M1", 2023, 2025)],
                ["2023.csv", "2025.csv"],
            )
