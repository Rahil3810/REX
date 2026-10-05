"""Tests for V1_WIDTH_FILTER controlled experiment (research-only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from core.features.generators.swings import SwingEvent, SwingKind, make_swing_id
from core.zones import AutomaticZoneGenerator, ZoneEvaluator
from core.zones.auto import SwingClusterZoneConfig
from core.zones.auto.atr import causal_atr
from models.bar import Bar
from research.width_filter_experiment import (
    PREDECLARED_MIN_WIDTH_ATR_RATIO,
    VARIANT_ID,
    WidthFilterExperimentConfig,
    apply_width_filter,
    passes_width_filter,
    run_single_window_comparison,
    run_width_filter_experiment,
    zone_width_atr_ratio,
)
from research.zones_pipeline import run_timeframe_pipeline


def _bar(i: int, *, high: float, low: float, close: float | None = None) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol="EURUSD",
        timestamp=datetime(2026, 1, 5, 0, 0) + timedelta(minutes=15 * i),
        open=mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=10.0,
    )


def _write_m1_csv(path: Path, *, hours: int = 12) -> None:
    lines = ["time,open,high,low,close,volume"]
    px = 1.1000
    start = datetime(2026, 1, 5, 0, 0, 0)
    for i in range(hours * 60):
        ts = start + timedelta(minutes=i)
        wave = 0.0002 * ((i % 23) - 11)
        o = px
        c = px + wave
        h = max(o, c) + 0.00008
        l = min(o, c) - 0.00008
        lines.append(
            f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')},"
            f"{o:.5f},{h:.5f},{l:.5f},{c:.5f},{i + 1}"
        )
        px = c
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class WidthFilterEligibilityTests(unittest.TestCase):
    def test_threshold_boundary(self) -> None:
        bars = [
            _bar(i, high=1.1000 + 0.0003, low=1.1000 - 0.0003, close=1.1000)
            for i in range(40)
        ]
        conf = 20
        swing = SwingEvent(
            id=make_swing_id("M15", SwingKind.HIGH, 18),
            timeframe="M15",
            kind=SwingKind.HIGH,
            price=1.1050,
            index=18,
            timestamp=bars[18].timestamp,
            confirmation_index=conf,
            confirmation_time=bars[conf].timestamp,
        )
        gen = AutomaticZoneGenerator(
            cluster_config=SwingClusterZoneConfig(
                atr_period=14,
                absolute_price_tolerance=0.001,
                single_swing_half_width_absolute=0.0005,
                min_contributing_swings=1,
            )
        )
        zones = gen.generate(
            bars, timeframe="M15", asof_index=len(bars) - 1, swings=[swing]
        )
        self.assertEqual(len(zones), 1)
        auto = zones[0]
        ratio = zone_width_atr_ratio(auto, bars)
        assert ratio is not None

        self.assertTrue(
            passes_width_filter(
                auto, bars, min_width_atr_ratio=ratio - 1e-12
            )
        )
        self.assertFalse(
            passes_width_filter(
                auto, bars, min_width_atr_ratio=ratio + 1e-6
            )
        )

    def test_missing_atr_rejects(self) -> None:
        bars = [_bar(i, high=1.101, low=1.099) for i in range(5)]
        conf = 4
        swing = SwingEvent(
            id=make_swing_id("M15", SwingKind.HIGH, 2),
            timeframe="M15",
            kind=SwingKind.HIGH,
            price=1.105,
            index=2,
            timestamp=bars[2].timestamp,
            confirmation_index=conf,
            confirmation_time=bars[conf].timestamp,
        )
        gen = AutomaticZoneGenerator(
            cluster_config=SwingClusterZoneConfig(min_contributing_swings=1)
        )
        zones = gen.generate(
            bars, timeframe="M15", asof_index=4, swings=[swing]
        )
        self.assertEqual(len(zones), 1)
        self.assertIsNone(causal_atr(bars, asof_index=conf, period=14))
        self.assertFalse(
            passes_width_filter(
                zones[0], bars, min_width_atr_ratio=0.01
            )
        )

    def test_causal_atr_no_future_leakage(self) -> None:
        bars = [
            _bar(i, high=1.1000 + 0.0003, low=1.1000 - 0.0003)
            for i in range(40)
        ]
        conf = 20
        swing = SwingEvent(
            id=make_swing_id("M15", SwingKind.HIGH, 18),
            timeframe="M15",
            kind=SwingKind.HIGH,
            price=1.1050,
            index=18,
            timestamp=bars[18].timestamp,
            confirmation_index=conf,
            confirmation_time=bars[conf].timestamp,
        )
        gen = AutomaticZoneGenerator(
            cluster_config=SwingClusterZoneConfig(
                atr_period=14,
                absolute_price_tolerance=0.001,
                single_swing_half_width_absolute=0.0005,
                min_contributing_swings=1,
            )
        )
        zones = gen.generate(
            bars, timeframe="M15", asof_index=len(bars) - 1, swings=[swing]
        )
        auto = zones[0]
        r1 = zone_width_atr_ratio(auto, bars)
        spiked = list(bars)
        b = spiked[conf + 8]
        spiked[conf + 8] = Bar(
            symbol=b.symbol,
            timestamp=b.timestamp,
            open=b.open,
            high=b.high + 0.05,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        r2 = zone_width_atr_ratio(auto, spiked)
        self.assertEqual(r1, r2)

    def test_baseline_unchanged_by_filter_module(self) -> None:
        bars = [
            _bar(i, high=1.1000 + 0.0003, low=1.1000 - 0.0003)
            for i in range(40)
        ]
        conf = 20
        swing = SwingEvent(
            id=make_swing_id("M15", SwingKind.HIGH, 18),
            timeframe="M15",
            kind=SwingKind.HIGH,
            price=1.1050,
            index=18,
            timestamp=bars[18].timestamp,
            confirmation_index=conf,
            confirmation_time=bars[conf].timestamp,
        )
        gen = AutomaticZoneGenerator(
            cluster_config=SwingClusterZoneConfig(
                atr_period=14,
                absolute_price_tolerance=0.001,
                single_swing_half_width_absolute=0.0005,
                min_contributing_swings=1,
            )
        )
        baseline = gen.generate(
            bars, timeframe="M15", asof_index=len(bars) - 1, swings=[swing]
        )
        retained, rejected = apply_width_filter(
            baseline, bars, config=WidthFilterExperimentConfig(min_width_atr_ratio=999.0)
        )
        self.assertEqual(len(baseline), 1)
        self.assertEqual(len(retained), 0)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(baseline[0].to_dict(), rejected[0].to_dict())


class WidthFilterExperimentIntegrationTests(unittest.TestCase):
    def test_predeclared_threshold_constant(self) -> None:
        self.assertEqual(PREDECLARED_MIN_WIDTH_ATR_RATIO, 0.35)
        cfg = WidthFilterExperimentConfig()
        self.assertEqual(cfg.variant_id, VARIANT_ID)
        self.assertEqual(cfg.min_width_atr_ratio, 0.35)

    def test_deterministic_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=12)
            from research.free_ohlc import build_research_dataset

            bars = build_research_dataset(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                skip_invalid_ohlc=True,
                target_timeframes=("M15",),
            ).bars("M15")
            a = run_single_window_comparison(bars, symbol="EURUSD")
            b = run_single_window_comparison(bars, symbol="EURUSD")
        self.assertEqual(a, b)

    def test_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=10)
            result = run_width_filter_experiment(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframe="M15",
            )
            out = Path(td) / "report.json"
            out.write_text(
                json.dumps(result.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("full_window", loaded)
        self.assertIn("chronological_thirds", loaded)
        self.assertIn("classification", loaded)
        self.assertEqual(loaded["config"]["min_width_atr_ratio"], 0.35)
        self.assertIn("baseline", loaded["full_window"])
        self.assertIn("experiment", loaded["full_window"])

    def test_pipeline_baseline_matches_direct_v1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=12)
            from research.free_ohlc import build_research_dataset

            bars = build_research_dataset(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                skip_invalid_ohlc=True,
                target_timeframes=("M15",),
            ).bars("M15")
            zones, evals, _ = run_timeframe_pipeline(
                bars, timeframe="M15", symbol="EURUSD"
            )
            cmp = run_single_window_comparison(bars, symbol="EURUSD")
        self.assertEqual(cmp["baseline"]["total_zones"], len(zones))
        self.assertEqual(
            cmp["baseline"]["total_interactions"],
            sum(e.sample_count for e in evals),
        )


if __name__ == "__main__":
    unittest.main()
