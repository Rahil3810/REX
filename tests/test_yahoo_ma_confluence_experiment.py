"""Tests for Yahoo → MA Confluence observational experiment (research-only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core.zones.auto.ma_confluence import MAConfluenceZoneConfig
from models.bar import Bar
from research.yahoo.adapter import (
    dataframe_to_bars,
    normalize_yahoo_timestamp,
    split_warmup_and_analysis,
)
from research.yahoo.ma_confluence_experiment import (
    run_yahoo_ma_confluence_experiment,
    write_experiment_json,
)


def _flat_bars(
    n: int = 500,
    *,
    start: datetime | None = None,
) -> list[Bar]:
    """Near-flat H1 series that triggers MA confluence after warmup."""
    start = start or datetime(2026, 1, 5, 0, 0, 0)
    bars: list[Bar] = []
    for i in range(n):
        wave = 0.00001 * ((i % 7) - 3)
        c = 1.1000 + wave
        bars.append(
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(hours=i),
                open=c,
                high=c + 0.00015,
                low=c - 0.00015,
                close=c,
                volume=0.0,
            )
        )
    return bars


class YahooTimestampTests(unittest.TestCase):
    def test_london_aware_timestamp_to_naive_utc(self) -> None:
        ts = pd.Timestamp("2026-09-21 00:00:00", tz=ZoneInfo("Europe/London"))
        # BST (+01:00) → 2026-09-20 23:00:00 UTC naive
        got = normalize_yahoo_timestamp(ts)
        self.assertIsNone(got.tzinfo)
        self.assertEqual(got, datetime(2026, 9, 20, 23, 0, 0))

    def test_ohlc_column_mapping(self) -> None:
        idx = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-06-01 10:00:00", tz=ZoneInfo("Europe/London")),
                pd.Timestamp("2026-06-01 11:00:00", tz=ZoneInfo("Europe/London")),
            ]
        )
        frame = pd.DataFrame(
            {
                "Open": [1.10, 1.11],
                "High": [1.12, 1.13],
                "Low": [1.09, 1.10],
                "Close": [1.11, 1.12],
                "Volume": [0, 0],
            },
            index=idx,
        )
        bars, notes = dataframe_to_bars(frame, symbol="EURUSD")
        self.assertEqual(notes, ())
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].open, 1.10)
        self.assertEqual(bars[0].high, 1.12)
        self.assertEqual(bars[0].low, 1.09)
        self.assertEqual(bars[0].close, 1.11)
        self.assertIsNone(bars[0].timestamp.tzinfo)
        # 10:00 London summer → 09:00 UTC
        self.assertEqual(bars[0].timestamp, datetime(2026, 6, 1, 9, 0, 0))


class WarmupSplitTests(unittest.TestCase):
    def test_warmup_precedes_analysis_window(self) -> None:
        bars = _flat_bars(500)
        warmup, analysis, a_start, a_end = split_warmup_and_analysis(
            bars, analysis_days=7, min_warmup_bars=300
        )
        self.assertGreaterEqual(len(warmup), 300)
        self.assertTrue(all(b.timestamp < a_start for b in warmup))
        self.assertTrue(all(b.timestamp >= a_start for b in analysis))
        self.assertEqual(analysis[-1].timestamp, a_end)
        self.assertEqual(warmup[-1].timestamp + timedelta(hours=1), analysis[0].timestamp)

    def test_insufficient_warmup_raises(self) -> None:
        bars = _flat_bars(50)
        with self.assertRaises(ValueError):
            split_warmup_and_analysis(bars, analysis_days=7, min_warmup_bars=300)


class YahooExperimentDeterminismTests(unittest.TestCase):
    def test_no_future_bars_in_generation_prefix(self) -> None:
        bars = _flat_bars(500)
        result = run_yahoo_ma_confluence_experiment(
            analysis_days=7,
            experiment_id="7D",
            bars=bars,
            min_warmup_bars=300,
        )
        analysis_end = datetime.fromisoformat(result.analysis_end)
        for row in result.candidates:
            created = datetime.fromisoformat(row["created_at"])
            self.assertLessEqual(created, analysis_end)
            self.assertGreaterEqual(
                created, datetime.fromisoformat(result.analysis_start)
            )

    def test_deterministic_repeated_runs(self) -> None:
        bars = _flat_bars(500)
        a = run_yahoo_ma_confluence_experiment(
            analysis_days=7, experiment_id="7D", bars=bars, min_warmup_bars=300
        )
        b = run_yahoo_ma_confluence_experiment(
            analysis_days=7, experiment_id="7D", bars=bars, min_warmup_bars=300
        )
        self.assertEqual(
            [c["zone_id"] for c in a.candidates],
            [c["zone_id"] for c in b.candidates],
        )
        self.assertEqual(
            [(c["low"], c["high"]) for c in a.candidates],
            [(c["low"], c["high"]) for c in b.candidates],
        )

    def test_uses_locked_v1_config(self) -> None:
        bars = _flat_bars(500)
        result = run_yahoo_ma_confluence_experiment(
            analysis_days=7, experiment_id="7D", bars=bars, min_warmup_bars=300
        )
        expected = MAConfluenceZoneConfig().to_dict()
        self.assertEqual(result.config["k_enter"], expected["k_enter"])
        self.assertEqual(result.config["k_exit"], expected["k_exit"])
        self.assertEqual(result.config["min_persist"], expected["min_persist"])
        self.assertEqual(result.config["generator_version"], expected["generator_version"])

    def test_json_export_roundtrip(self) -> None:
        bars = _flat_bars(500)
        result = run_yahoo_ma_confluence_experiment(
            analysis_days=7, experiment_id="7D", bars=bars, min_warmup_bars=300
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            write_experiment_json(result, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["data_source"], "yahoo")
            self.assertEqual(payload["ticker"], "EURUSD=X")
            self.assertIn("quality_audit", payload)
            self.assertIn("candidates", payload)

    def test_filter_excludes_warmup_creations(self) -> None:
        bars = _flat_bars(500)
        # Run generator-style: create a fake GeneratedZone-like filter via experiment
        result = run_yahoo_ma_confluence_experiment(
            analysis_days=7, experiment_id="7D", bars=bars, min_warmup_bars=300
        )
        a_start = datetime.fromisoformat(result.analysis_start)
        for row in result.candidates:
            self.assertGreaterEqual(datetime.fromisoformat(row["created_at"]), a_start)


if __name__ == "__main__":
    unittest.main()
