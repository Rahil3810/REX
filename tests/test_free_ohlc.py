"""Focused tests for research free-OHLC parsers."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from research.free_ohlc.formats import (
    TimezonePolicy,
    VolumeSemantics,
    detect_format,
    in_date_range,
    load_free_ohlc_csv,
    locate_data_files,
    ohlc_valid,
    parse_epoch_ms_ohlc_line,
    parse_iso_z_ohlcv_line,
)


class FreeOhlcFormatTests(unittest.TestCase):
    def test_iso_z_parse_utc_and_tick_volume(self) -> None:
        bar = parse_iso_z_ohlcv_line(
            "2026-01-04T22:07:00Z,1.17216,1.17216,1.17206,1.17207,2"
        )
        assert bar is not None
        self.assertEqual(bar.timestamp, datetime(2026, 1, 4, 22, 7, 0))
        self.assertEqual(bar.volume, 2.0)
        self.assertEqual(bar.volume_semantics, VolumeSemantics.TICK_VOLUME)
        self.assertEqual(bar.source_timezone_policy, TimezonePolicy.CONFIRMED_UTC)
        self.assertTrue(ohlc_valid(bar.open, bar.high, bar.low, bar.close))

    def test_iso_z_rejects_naive_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            parse_iso_z_ohlcv_line("2026-01-04T22:07:00,1.17,1.17,1.17,1.17,1")

    def test_epoch_ms_assumed_utc(self) -> None:
        # 2026-08-20 00:00:00 UTC
        bar = parse_epoch_ms_ohlc_line("1787184000000,1.16742,1.16762,1.16742,1.16761")
        assert bar is not None
        self.assertEqual(bar.timestamp, datetime(2026, 8, 20, 0, 0, 0))
        self.assertIsNone(bar.volume)
        self.assertEqual(bar.volume_semantics, VolumeSemantics.NONE)
        self.assertEqual(bar.source_timezone_policy, TimezonePolicy.ASSUMED_UTC_EPOCH_MS)

    def test_ohlc_invalid_high_below_low(self) -> None:
        self.assertFalse(ohlc_valid(1.2, 1.1, 1.15, 1.18))

    def test_date_filter_and_duplicates_order_via_load(self) -> None:
        payload = (
            "# comment\n"
            "time,open,high,low,close,volume\n"
            "2026-01-05T00:00:00Z,1.10,1.11,1.09,1.105,10\n"
            "2026-01-05T00:01:00Z,1.105,1.12,1.10,1.11,8\n"
            "2026-01-06T00:00:00Z,1.11,1.13,1.10,1.12,9\n"
            "2026-01-08T00:00:00Z,1.12,1.14,1.11,1.13,7\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "EURUSD_1m.csv"
            path.write_text(payload, encoding="utf-8")
            fmt, bars = load_free_ohlc_csv(
                path, start=date(2026, 1, 5), end=date(2026, 1, 6)
            )
            self.assertEqual(fmt, "iso_z_ohlcv")
            self.assertEqual(len(bars), 3)
            self.assertTrue(in_date_range(bars[0].timestamp, date(2026, 1, 5), date(2026, 1, 6)))
            # deterministic order as file order
            self.assertEqual(
                [b.timestamp for b in bars],
                [
                    datetime(2026, 1, 5, 0, 0),
                    datetime(2026, 1, 5, 0, 1),
                    datetime(2026, 1, 6, 0, 0),
                ],
            )

    def test_detect_formats(self) -> None:
        self.assertEqual(
            detect_format(["time,open,high,low,close,volume", "2026-01-01T00:00:00Z,1,1,1,1,1"]),
            "iso_z_ohlcv",
        )
        self.assertEqual(
            detect_format(["timestamp,open,high,low,close", "1787184000000,1,1,1,1"]),
            "epoch_ms_ohlc",
        )

    def test_locate_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "EURUSD_1m.csv").write_text(
                "time,open,high,low,close,volume\n2026-01-01T00:00:00Z,1,1,1,1,1\n",
                encoding="utf-8",
            )
            found = locate_data_files(root, "EURUSD")
            self.assertEqual([p.name for p in found], ["EURUSD_1m.csv"])


if __name__ == "__main__":
    unittest.main()
