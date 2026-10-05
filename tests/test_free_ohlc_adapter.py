"""Unit tests for research free-OHLC → canonical Bar adapter."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from research.free_ohlc.adapter import FreeOhlcAdapterError, load_free_ohlc


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class FreeOhlcAdapterTests(unittest.TestCase):
    def test_valid_row_to_canonical_bar_utc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "EURUSD_1m.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,12\n",
            )
            result = load_free_ohlc(path, symbol="EURUSD", timeframe="M1")
            self.assertEqual(len(result.bars), 1)
            bar = result.bars[0]
            self.assertEqual(bar.symbol, "EURUSD")
            self.assertEqual(bar.timestamp, datetime(2026, 1, 5, 10, 0, 0))
            self.assertEqual(bar.volume, 12.0)
            self.assertEqual(result.stats.volume_type, "tick_volume")
            self.assertEqual(result.stats.timezone_policy, "CONFIRMED_UTC")

    def test_invalid_ohlc_rejected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "x.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:00:00Z,1.10,1.09,1.08,1.085,1\n",  # high < open path invalid
            )
            with self.assertRaises(FreeOhlcAdapterError):
                load_free_ohlc(path, symbol="EURUSD")

    def test_invalid_ohlc_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "x.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:00:00Z,1.10,1.09,1.08,1.085,1\n"
                "2026-01-05T10:01:00Z,1.10,1.11,1.09,1.105,2\n",
            )
            result = load_free_ohlc(path, symbol="EURUSD", skip_invalid_ohlc=True)
            self.assertEqual(result.stats.rows_dropped_invalid, 1)
            self.assertEqual(result.stats.bar_count, 1)
            self.assertEqual(result.bars[0].timestamp, datetime(2026, 1, 5, 10, 1, 0))

    def test_duplicate_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "x.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,1\n"
                "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,1\n",
            )
            with self.assertRaises(FreeOhlcAdapterError):
                load_free_ohlc(path, symbol="EURUSD")

    def test_out_of_order_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "x.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:01:00Z,1.10,1.11,1.09,1.105,1\n"
                "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,1\n",
            )
            with self.assertRaises(FreeOhlcAdapterError):
                load_free_ohlc(path, symbol="EURUSD")

    def test_date_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                Path(tmp) / "x.csv",
                "time,open,high,low,close,volume\n"
                "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,1\n"
                "2026-01-06T10:00:00Z,1.10,1.11,1.09,1.105,1\n"
                "2026-01-07T10:00:00Z,1.10,1.11,1.09,1.105,1\n",
            )
            result = load_free_ohlc(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 6),
                end=date(2026, 1, 6),
            )
            self.assertEqual(result.stats.bar_count, 1)
            self.assertEqual(result.stats.rows_dropped_date_filter, 2)

    def test_tick_volume_preserved_and_deterministic(self) -> None:
        payload = (
            "time,open,high,low,close,volume\n"
            "2026-01-05T10:00:00Z,1.10,1.11,1.09,1.105,7\n"
            "2026-01-05T10:01:00Z,1.105,1.12,1.10,1.11,9\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "x.csv", payload)
            a = load_free_ohlc(path, symbol="eurusd")
            b = load_free_ohlc(path, symbol="EURUSD")
            self.assertEqual([x.volume for x in a.bars], [7.0, 9.0])
            self.assertEqual(a.bars, b.bars)
            self.assertEqual(a.stats.volume_type, "tick_volume")


if __name__ == "__main__":
    unittest.main()
