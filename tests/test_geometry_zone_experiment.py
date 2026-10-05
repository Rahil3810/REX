"""Tests for geometry/lifecycle zone outcome diagnostic."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from core.zones.auto.atr import causal_atr
from models.bar import Bar
from models.zone import ZoneKind
from research.geometry_zone_experiment import (
    age_bars_bucket,
    compute_creation_geometry,
    penetration_at_entry,
    recent_range,
    run_geometry_lifecycle_on_zones,
    touch_bucket,
    width_atr_bucket,
    zone_width,
)
from research.zones_pipeline import PIPELINE_VERSION, run_research_zones_smoke


def _bar(
    i: int,
    *,
    high: float,
    low: float,
    close: float | None = None,
    open_: float | None = None,
) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol="EURUSD",
        timestamp=datetime(2026, 1, 5, 0, 0) + timedelta(minutes=15 * i),
        open=open_ if open_ is not None else mid,
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


class GeometryHelpersTests(unittest.TestCase):
    def test_zone_width_and_buckets(self) -> None:
        self.assertEqual(width_atr_bucket(0.4), "lt_0.5")
        self.assertEqual(width_atr_bucket(0.7), "0.5_to_1")
        self.assertEqual(width_atr_bucket(1.5), "1_to_2")
        self.assertEqual(width_atr_bucket(2.5), "gt_2")
        self.assertEqual(width_atr_bucket(None), "atr_unavailable")
        self.assertEqual(age_bars_bucket(2), "lt_1h")
        self.assertEqual(age_bars_bucket(10), "1h_to_4h")
        self.assertEqual(age_bars_bucket(50), "4h_to_24h")
        self.assertEqual(age_bars_bucket(100), "gt_24h")
        self.assertEqual(age_bars_bucket(None), "no_interaction")
        self.assertEqual(touch_bucket(0), "0")
        self.assertEqual(touch_bucket(3), "3_plus")

    def test_penetration_normalization(self) -> None:
        bar = _bar(0, high=1.1015, low=1.1005, close=1.1010)
        pen = penetration_at_entry(1.100, 1.102, ZoneKind.DEMAND, bar)
        self.assertGreater(pen["wick_depth"], 0)
        self.assertIsNotNone(pen["wick_depth_over_width"])
        self.assertTrue(pen["close_inside"])
        self.assertFalse(pen["close_through"])

        through = _bar(1, high=1.101, low=1.095, close=1.096)
        pen2 = penetration_at_entry(1.100, 1.102, ZoneKind.DEMAND, through)
        self.assertTrue(pen2["close_through"])

    def test_atr_normalization_causal(self) -> None:
        bars = [
            _bar(i, high=1.10 + 0.001, low=1.10 - 0.001, close=1.10)
            for i in range(30)
        ]
        # Spike only in the future relative to index 20.
        future = list(bars)
        future[25] = _bar(25, high=1.20, low=1.19, close=1.195)
        atr_prefix = causal_atr(bars, asof_index=20, period=14)
        atr_full = causal_atr(future, asof_index=20, period=14)
        self.assertEqual(atr_prefix, atr_full)
        atr_late = causal_atr(future, asof_index=25, period=14)
        self.assertNotEqual(atr_prefix, atr_late)


class GeometryLifecycleExperimentTests(unittest.TestCase):
    def test_creation_geometry_no_lookahead(self) -> None:
        from core.features.generators.swings import SwingKind, make_swing_id, SwingEvent
        from core.zones import AutomaticZoneGenerator
        from core.zones.auto import SwingClusterZoneConfig

        bars = [
            _bar(
                i,
                high=1.1000 + 0.0003 + (0.0001 if i % 3 == 0 else 0),
                low=1.1000 - 0.0003,
                close=1.1000,
            )
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
        full = compute_creation_geometry(
            auto, bars, symbol="EURUSD", timeframe="M15"
        )
        prefix = compute_creation_geometry(
            auto, bars[: conf + 1], symbol="EURUSD", timeframe="M15"
        )
        self.assertEqual(full.absolute_width, prefix.absolute_width)
        self.assertEqual(full.atr_at_creation, prefix.atr_at_creation)
        self.assertEqual(full.width_over_atr, prefix.width_over_atr)
        self.assertEqual(zone_width(auto), full.absolute_width)
        # Future spike after confirmation must not change creation ATR.
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
        spiked_geo = compute_creation_geometry(
            auto, spiked, symbol="EURUSD", timeframe="M15"
        )
        self.assertEqual(spiked_geo.atr_at_creation, full.atr_at_creation)
        self.assertIsNotNone(full.atr_at_creation)

    def test_lifecycle_age_and_touches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=14)
            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=False,
                include_geometry_lifecycle=True,
            )
        geo = result.geometry_lifecycle_experiment
        assert geo is not None
        for life in geo["lifecycles"]:
            if life["age_bars_to_first_interaction"] is not None:
                self.assertGreaterEqual(life["age_bars_to_first_interaction"], 1)
                self.assertEqual(
                    life["age_bucket_first_interaction"],
                    age_bars_bucket(life["age_bars_to_first_interaction"]),
                )
        for ix in geo["interaction_features"]:
            self.assertEqual(
                ix["prior_touches_bucket"], touch_bucket(ix["prior_touches"])
            )
            self.assertEqual(ix["prior_touches"], ix["interaction_index"])

    def test_empty_insufficient_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.csv"
            path.write_text("time,open,high,low,close,volume\n", encoding="utf-8")
            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=False,
                include_geometry_lifecycle=True,
            )
        self.assertIsNone(result.geometry_lifecycle_experiment)

        empty = run_geometry_lifecycle_on_zones(
            (), (), (), symbol="EURUSD", timeframe="M15"
        )
        self.assertEqual(empty.baseline["zone_count"], 0)
        self.assertTrue(
            empty.aggregates["by_width_over_atr"]["lt_0.5"]["sample_size"][
                "too_small_to_interpret"
            ]
        )

    def test_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=12)
            kwargs = dict(
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=False,
                include_geometry_lifecycle=True,
            )
            a = run_research_zones_smoke(path, **kwargs)
            b = run_research_zones_smoke(path, **kwargs)
        assert a.geometry_lifecycle_experiment is not None
        assert b.geometry_lifecycle_experiment is not None
        self.assertEqual(
            a.geometry_lifecycle_experiment["aggregates"],
            b.geometry_lifecycle_experiment["aggregates"],
        )
        self.assertEqual(
            a.geometry_lifecycle_experiment["diagnosis"]["conclusion_code"],
            b.geometry_lifecycle_experiment["diagnosis"]["conclusion_code"],
        )

    def test_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=10)
            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=True,
                include_structure_context=False,
                include_geometry_lifecycle=True,
            )
            payload = result.to_dict()
            out = Path(td) / "out.json"
            out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            loaded = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(loaded["pipeline_version"], PIPELINE_VERSION)
        self.assertIn("geometry_lifecycle_experiment", loaded)
        geo = loaded["geometry_lifecycle_experiment"]
        self.assertIn("baseline", geo)
        self.assertIn("aggregates", geo)
        self.assertIn("by_width_over_atr", geo["aggregates"])
        self.assertIn("diagnosis", geo)
        self.assertIn("sample_size", geo["aggregates"]["by_width_over_atr"]["lt_0.5"])

    def test_recent_range_helper(self) -> None:
        bars = [
            _bar(0, high=1.10, low=1.09),
            _bar(1, high=1.11, low=1.08),
            _bar(2, high=1.12, low=1.10),
        ]
        self.assertAlmostEqual(recent_range(bars, asof_index=2, lookback=3), 0.04)
        self.assertIsNone(recent_range(bars, asof_index=-1))


if __name__ == "__main__":
    unittest.main()
