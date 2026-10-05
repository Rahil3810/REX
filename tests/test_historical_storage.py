"""Tests for yearly historical storage."""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from historical.parser import HistoricalDataParser
from historical.storage import HistoricalStorage
from models.bar import Bar


def _write_csv_only(storage: HistoricalStorage, symbol: str, timeframe: str, year: int) -> Path:
    path = storage.year_path(symbol, timeframe, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        f"{year}-06-01T00:00:00Z,1.10,1.11,1.09,1.105,1\n",
        encoding="utf-8",
    )
    return path


def _write_meta(
    storage: HistoricalStorage,
    symbol: str,
    timeframe: str,
    year: int,
    start: date,
    end: date,
) -> Path:
    path = storage.year_path(symbol, timeframe, year)
    meta = path.with_suffix(".meta.json")
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(
            {
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "year": year,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return meta


class HistoricalStorageTests(unittest.TestCase):
    def test_writes_canonical_year_partition_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            path = storage.write_year(
                "eurusd",
                "m1",
                2024,
                [Bar("EURUSD", datetime(2024, 1, 2), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
            self.assertEqual(path, Path(directory) / "EURUSD" / "M1" / "2024.csv")
            self.assertTrue(
                storage.has_coverage("EURUSD", "M1", date(2024, 2, 1), date(2024, 3, 1))
            )
            self.assertEqual(len(HistoricalDataParser().parse_file(path, "EURUSD")), 1)

    def test_lists_only_existing_years_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            for year in (2023, 2025):
                storage.write_year(
                    "EURUSD", "M1", year, [], date(year, 1, 1), date(year, 12, 31)
                )
            self.assertEqual(
                [
                    path.name
                    for path in storage.existing_files("EURUSD", "M1", 2023, 2025)
                ],
                ["2023.csv", "2025.csv"],
            )


class HasCoverageFailClosedTests(unittest.TestCase):
    """P0-2: has_coverage must not invent coverage from CSV presence alone."""

    def test_missing_metadata_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            _write_csv_only(storage, "EURUSD", "M1", 2024)
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 1), date(2024, 12, 31)
                )
            )

    def test_valid_metadata_fully_covered_range_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 6, 1), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
            self.assertTrue(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 2, 1), date(2024, 11, 30)
                )
            )

    def test_partial_range_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            # Metadata only claims Jan–Jun; request includes July.
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 3, 1), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 6, 30),
            )
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 1), date(2024, 7, 1)
                )
            )

    def test_multi_year_only_first_year_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 12, 15), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
            # 2025 partition/metadata absent.
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 12, 1), date(2025, 1, 15)
                )
            )

    def test_multi_year_fully_covered_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 12, 15), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
            storage.write_year(
                "EURUSD",
                "M1",
                2025,
                [Bar("EURUSD", datetime(2025, 1, 10), 1.1, 1.2, 1.0, 1.15)],
                date(2025, 1, 1),
                date(2025, 12, 31),
            )
            self.assertTrue(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 12, 1), date(2025, 1, 15)
                )
            )

    def test_malformed_json_metadata_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            path = _write_csv_only(storage, "EURUSD", "M1", 2024)
            path.with_suffix(".meta.json").write_text("{not-json", encoding="utf-8")
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 1), date(2024, 1, 31)
                )
            )

    def test_malformed_coverage_fields_return_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            path = _write_csv_only(storage, "EURUSD", "M1", 2024)
            path.with_suffix(".meta.json").write_text(
                json.dumps(
                    {
                        "symbol": "EURUSD",
                        "timeframe": "M1",
                        "year": 2024,
                        "start_date": "not-a-date",
                        "end_date": "2024-12-31",
                    }
                ),
                encoding="utf-8",
            )
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 1), date(2024, 1, 31)
                )
            )

    def test_missing_coverage_fields_return_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            path = _write_csv_only(storage, "EURUSD", "M1", 2024)
            path.with_suffix(".meta.json").write_text(
                json.dumps({"symbol": "EURUSD", "year": 2024}),
                encoding="utf-8",
            )
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 1), date(2024, 1, 31)
                )
            )

    def test_inclusive_boundary_exact_start_and_end(self) -> None:
        """Coverage dates are inclusive; exact endpoints must satisfy the request."""
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 3, 15), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 3, 1),
                date(2024, 3, 31),
            )
            # Exact inclusive bounds → covered.
            self.assertTrue(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 3, 1), date(2024, 3, 31)
                )
            )
            # One day before claimed start → not covered.
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 2, 28), date(2024, 3, 31)
                )
            )
            # One day after claimed end → not covered.
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 3, 1), date(2024, 4, 1)
                )
            )

    def test_inverted_request_range_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            storage.write_year(
                "EURUSD",
                "M1",
                2024,
                [Bar("EURUSD", datetime(2024, 1, 2), 1.1, 1.2, 1.0, 1.15)],
                date(2024, 1, 1),
                date(2024, 12, 31),
            )
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 6, 1), date(2024, 1, 1)
                )
            )

    def test_inverted_metadata_coverage_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = HistoricalStorage(Path(directory))
            _write_csv_only(storage, "EURUSD", "M1", 2024)
            _write_meta(
                storage,
                "EURUSD",
                "M1",
                2024,
                date(2024, 12, 31),
                date(2024, 1, 1),
            )
            self.assertFalse(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 6, 1), date(2024, 6, 30)
                )
            )
