"""Tests for retrying and resumable duka orchestration."""

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from historical.config import load_historical_config
from historical.downloader import HistoricalDownloader


class FakeDukaRunner:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def download(self, symbol, start_date, end_date, destination, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary duka failure")
        path = destination / "duka.csv"
        path.write_text(
            "time,open,close,high,low\n"
            f"{start_date.isoformat()} 00:00:00.000000,1.10,1.11,1.12,1.09\n",
            encoding="utf-8",
        )
        return path


class HistoricalDownloaderTests(unittest.TestCase):
    def test_retries_then_writes_expected_year_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                load_historical_config(),
                symbols=("EURUSD",), data_directory=Path(directory), retries=2,
                retry_delay_seconds=0,
            )
            runner = FakeDukaRunner(failures=1)
            paths = HistoricalDownloader(
                config, runner=runner, sleeper=lambda _: None
            ).download(start_date=date(2024, 1, 1), end_date=date(2024, 12, 31))
            self.assertEqual(runner.calls, 2)
            self.assertEqual(paths[0], Path(directory) / "EURUSD" / "M1" / "2024.csv")
            self.assertTrue(paths[0].exists())

    def test_skips_partition_with_complete_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                load_historical_config(), symbols=("EURUSD",),
                data_directory=Path(directory), retries=0,
            )
            runner = FakeDukaRunner()
            downloader = HistoricalDownloader(config, runner=runner)
            requested = (date(2024, 1, 1), date(2024, 12, 31))
            downloader.download(start_date=requested[0], end_date=requested[1])
            downloader.download(start_date=requested[0], end_date=requested[1])
            self.assertEqual(runner.calls, 1)
