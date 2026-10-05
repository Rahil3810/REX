"""Tests for Zone V1 geometry audit (research-only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.features.generators.swings import SwingEvent, SwingKind, make_swing_id
from core.zones import AutomaticZoneGenerator, SwingClusterZoneConfig
from core.zones.auto.atr import causal_atr
from models.bar import Bar
from research.zone_geometry_audit import (
    audit_zone_geometry,
    distribution_summary,
    expected_cluster_boundaries,
    lookup_swings_by_id,
    run_zone_geometry_audit,
    select_representative_samples,
    summarize_records,
)


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


def _swing(
    kind: SwingKind,
    *,
    index: int,
    price: float,
    confirmation_index: int,
    timeframe: str = "M15",
) -> SwingEvent:
    return SwingEvent(
        id=make_swing_id(timeframe, kind, index),
        timeframe=timeframe,
        kind=kind,
        price=price,
        index=index,
        timestamp=datetime(2026, 1, 5, 0, 0) + timedelta(minutes=15 * index),
        confirmation_index=confirmation_index,
        confirmation_time=datetime(2026, 1, 5, 0, 0)
        + timedelta(minutes=15 * confirmation_index),
    )


def _write_m1_csv(path: Path, *, hours: int = 12) -> None:
    lines = ["time,open,high,low,close,volume"]
    px = 1.1000
    start = datetime(2026, 1, 5, 0, 0, 0)
    for i in range(hours * 60):
        ts = start + timedelta(minutes=i)
        wave = 0.00005 * ((i % 23) - 11)
        o = px
        c = px + wave
        h = max(o, c) + 0.00015
        l = min(o, c) - 0.00015
        if h < l:
            h, l = l, h
        lines.append(f"{ts:%Y-%m-%d %H:%M:%S},{o:.5f},{h:.5f},{l:.5f},{c:.5f},10")
        px = c
    path.write_text("\n".join(lines), encoding="utf-8")


class ZoneGeometryAuditTests(unittest.TestCase):
    def test_expected_cluster_boundaries_single_swing(self) -> None:
        low, high, geo = expected_cluster_boundaries([1.1050], half_width=0.0005)
        self.assertEqual(geo, "single_swing_expanded")
        self.assertAlmostEqual(low, 1.1045)
        self.assertAlmostEqual(high, 1.1055)

    def test_expected_cluster_boundaries_multi_swing(self) -> None:
        low, high, geo = expected_cluster_boundaries(
            [1.1000, 1.1008], half_width=0.0005
        )
        self.assertEqual(geo, "multi_swing_envelope")
        self.assertAlmostEqual(low, 1.1000)
        self.assertAlmostEqual(high, 1.1008)

    def test_audit_matches_v1_single_swing(self) -> None:
        cfg = SwingClusterZoneConfig(
            atr_period=10_000,
            single_swing_half_width_absolute=0.0005,
            absolute_price_tolerance=0.0010,
        )
        bars = [_bar(i, high=1.10, low=1.09) for i in range(30)]
        gen = AutomaticZoneGenerator(cluster_config=cfg)
        swing = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        zones = gen.generate(bars, timeframe="M15", asof_index=20, swings=[swing])
        swings_by_id = {swing.id: swing}
        rec = audit_zone_geometry(zones[0], bars, swings_by_id, config=cfg)
        self.assertTrue(rec.boundary_matches_implementation)
        self.assertEqual(rec.geometry_type, "single_swing_expanded")
        self.assertAlmostEqual(rec.absolute_width, 0.0010)

    def test_audit_matches_v1_multi_swing(self) -> None:
        cfg = SwingClusterZoneConfig(
            atr_period=10_000,
            single_swing_half_width_absolute=0.0005,
            absolute_price_tolerance=0.0010,
        )
        bars = [_bar(i, high=1.10, low=1.09) for i in range(40)]
        gen = AutomaticZoneGenerator(cluster_config=cfg)
        swings = [
            _swing(SwingKind.HIGH, index=5, price=1.1000, confirmation_index=7),
            _swing(SwingKind.HIGH, index=12, price=1.1008, confirmation_index=14),
        ]
        zones = gen.generate(bars, timeframe="M15", asof_index=25, swings=swings)
        swings_by_id = {s.id: s for s in swings}
        rec = audit_zone_geometry(zones[0], bars, swings_by_id, config=cfg)
        self.assertTrue(rec.boundary_matches_implementation)
        self.assertEqual(rec.geometry_type, "multi_swing_envelope")
        self.assertAlmostEqual(rec.absolute_width, 0.0008)

    def test_causal_atr_at_origin_no_future_leakage(self) -> None:
        bars = [_bar(i, high=1.10 + i * 0.00001, low=1.09) for i in range(40)]
        atr_before = causal_atr(bars[:20], asof_index=19, period=14)
        bars[25] = _bar(25, high=1.50, low=1.40)
        atr_after = causal_atr(bars, asof_index=19, period=14)
        self.assertAlmostEqual(atr_before or 0.0, atr_after or 0.0, places=10)

    def test_distribution_summary_percentiles(self) -> None:
        dist = distribution_summary([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        self.assertEqual(dist["count"], 10)
        self.assertEqual(dist["min"], 1.0)
        self.assertEqual(dist["max"], 10.0)
        self.assertEqual(dist["median"], 5.5)
        self.assertIsNotNone(dist["p10"])
        self.assertIsNotNone(dist["p90"])

    def test_deterministic_audit_on_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "sample.csv"
            _write_m1_csv(csv_path, hours=8)
            a = run_zone_geometry_audit(
                csv_path, start=datetime(2026, 1, 5).date(), end=datetime(2026, 1, 5).date()
            )
            b = run_zone_geometry_audit(
                csv_path, start=datetime(2026, 1, 5).date(), end=datetime(2026, 1, 5).date()
            )
            self.assertEqual(
                a.full_window.get("zone_count"),
                b.full_window.get("zone_count"),
            )
            self.assertEqual(
                a.full_window.get("boundary_verification"),
                b.full_window.get("boundary_verification"),
            )

    def test_serialization_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "sample.csv"
            _write_m1_csv(csv_path, hours=8)
            result = run_zone_geometry_audit(
                csv_path, start=datetime(2026, 1, 5).date(), end=datetime(2026, 1, 5).date()
            )
            payload = result.to_dict()
            text = json.dumps(payload, default=str)
            loaded = json.loads(text)
            self.assertEqual(loaded["audit_version"], result.audit_version)
            self.assertIn("conclusion", loaded)
            self.assertIn("full_window", loaded)

    def test_baseline_v1_generator_unchanged_by_audit(self) -> None:
        """Audit is read-only — generation output identical before/after audit."""
        cfg = SwingClusterZoneConfig(
            atr_period=10_000,
            single_swing_half_width_absolute=0.0005,
            absolute_price_tolerance=0.0010,
        )
        bars = [_bar(i, high=1.10, low=1.09) for i in range(30)]
        gen = AutomaticZoneGenerator(cluster_config=cfg)
        swing = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        before = gen.generate(bars, timeframe="M15", asof_index=20, swings=[swing])
        swings_by_id = lookup_swings_by_id(
            bars, symbol="EURUSD", timeframe="M15", asof_index=20
        )
        _ = audit_zone_geometry(before[0], bars, swings_by_id, config=cfg)
        after = gen.generate(bars, timeframe="M15", asof_index=20, swings=[swing])
        self.assertEqual(before[0].zone.low, after[0].zone.low)
        self.assertEqual(before[0].zone.high, after[0].zone.high)


if __name__ == "__main__":
    unittest.main()
