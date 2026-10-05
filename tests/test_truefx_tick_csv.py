"""Unit tests for TrueFX research tick CSV parsing (format fixtures only)."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path

from research.truefx.tick_csv import (
    in_date_range,
    iter_truefx_csv_lines,
    locate_truefx_files,
    normalize_symbol,
    parse_truefx_tick_line,
    parse_truefx_timestamp,
    tick_prices_valid,
)


class TrueFXTickCsvTests(unittest.TestCase):
    def test_parse_millisecond_timestamp(self) -> None:
        ts = parse_truefx_timestamp("20241009 14:40:21.818")
        self.assertEqual(ts, datetime(2024, 10, 9, 14, 40, 21, 818000))

    def test_parse_tick_line_bid_ask_mid_spread(self) -> None:
        tick = parse_truefx_tick_line("EUR/USD,20241009 14:40:21.818,1.09476,1.09478")
        assert tick is not None
        self.assertEqual(normalize_symbol(tick.pair), "EURUSD")
        self.assertEqual(tick.bid, 1.09476)
        self.assertEqual(tick.ask, 1.09478)
        self.assertAlmostEqual(tick.midpoint, 1.09477)
        self.assertAlmostEqual(tick.spread, 0.00002)
        self.assertTrue(tick_prices_valid(tick))

    def test_rejects_ask_below_bid(self) -> None:
        tick = parse_truefx_tick_line("EUR/USD,20241009 14:40:21.818,1.10,1.09")
        assert tick is not None
        self.assertFalse(tick_prices_valid(tick))

    def test_rejects_wrong_field_count(self) -> None:
        with self.assertRaises(ValueError):
            parse_truefx_tick_line("EUR/USD,20241009 14:40:21.818,1.09")

    def test_skips_headerish_rows(self) -> None:
        self.assertIsNone(parse_truefx_tick_line("pair,timestamp,bid,ask"))

    def test_date_range_filter(self) -> None:
        ts = datetime(2024, 10, 9, 12, 0, 0)
        self.assertTrue(in_date_range(ts, date(2024, 10, 9), date(2024, 10, 9)))
        self.assertFalse(in_date_range(ts, date(2024, 10, 10), date(2024, 10, 11)))

    def test_locate_and_read_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_name = "EURUSD-2024-10.csv"
            payload = (
                "EUR/USD,20241009 14:40:21.818,1.09476,1.09478\n"
                "EUR/USD,20241009 14:40:21.912,1.09473,1.09482\n"
            )
            zip_path = root / "EURUSD-2024-10.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(csv_name, payload)
            found = locate_truefx_files(root, "EURUSD")
            self.assertEqual([p.name for p in found], ["EURUSD-2024-10.zip"])
            lines = list(iter_truefx_csv_lines(zip_path))
            self.assertEqual(len(lines), 2)
            tick = parse_truefx_tick_line(lines[0])
            assert tick is not None
            self.assertEqual(tick.bid, 1.09476)


if __name__ == "__main__":
    unittest.main()
