"""Tests for causal structure-context zone outcome experiment."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from core.zones import AutomaticZoneGenerator, ZoneEvaluator
from core.zones.auto.evidence import AutomaticZone, ZoneEvidence, ZoneLifecycleStatus
from models.bar import Bar
from models.market_structure import MarketTrend
from models.zone import Zone, ZoneKind, ZoneSource
from research.structure_zone_experiment import (
    ALIGNMENT_ALIGNED,
    ALIGNMENT_NEUTRAL,
    ALIGNMENT_OPPOSED,
    STRUCTURE_BEARISH,
    STRUCTURE_BULLISH,
    STRUCTURE_NEUTRAL,
    alignment_bucket_from_zone_and_trend,
    classify_zone_structure_context,
    run_structure_context_on_zones,
    structure_bucket_from_trend,
)
from research.zones_pipeline import PIPELINE_VERSION, run_research_zones_smoke


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


def _write_m1_csv(path: Path, *, hours: int = 10) -> None:
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


def _synthetic_zone(
    *,
    zone_id: int,
    kind: ZoneKind,
    conf_index: int,
    conf_time: datetime,
) -> AutomaticZone:
    zone = Zone(
        id=zone_id,
        name=f"z{zone_id}",
        low=1.10,
        high=1.101,
        timeframe="M15",
        kind=kind,
        strength=1,
        source=ZoneSource.AUTOMATIC,
    )
    evidence = ZoneEvidence(
        method_id="swing_cluster_zone_v1",
        origin_swing_id="s1",
        origin_index=max(0, conf_index - 2),
        origin_timestamp=conf_time - timedelta(minutes=30),
        origin_confirmation_index=conf_index,
        origin_confirmation_time=conf_time,
        contributing_swing_ids=("s1",),
        contributing_swing_count=1,
        touch_count=0,
        mitigation_count=0,
        status=ZoneLifecycleStatus.FRESH,
        zone_age_bars=0,
        departure_move=None,
        reaction_magnitude=None,
        bos_associated=False,
        atr_used=None,
        cluster_tolerance=0.0001,
        asof_index=conf_index,
        asof_time=conf_time,
    )
    return AutomaticZone(zone=zone, evidence=evidence)


class StructureBucketMappingTests(unittest.TestCase):
    def test_structure_and_alignment_mapping(self) -> None:
        self.assertEqual(
            structure_bucket_from_trend(MarketTrend.BULLISH), STRUCTURE_BULLISH
        )
        self.assertEqual(
            structure_bucket_from_trend(MarketTrend.BEARISH), STRUCTURE_BEARISH
        )
        self.assertEqual(
            structure_bucket_from_trend(MarketTrend.RANGING), STRUCTURE_NEUTRAL
        )
        self.assertEqual(
            structure_bucket_from_trend(MarketTrend.UNKNOWN), STRUCTURE_NEUTRAL
        )

        self.assertEqual(
            alignment_bucket_from_zone_and_trend(ZoneKind.DEMAND, MarketTrend.BULLISH),
            ALIGNMENT_ALIGNED,
        )
        self.assertEqual(
            alignment_bucket_from_zone_and_trend(ZoneKind.SUPPLY, MarketTrend.BEARISH),
            ALIGNMENT_ALIGNED,
        )
        self.assertEqual(
            alignment_bucket_from_zone_and_trend(ZoneKind.DEMAND, MarketTrend.BEARISH),
            ALIGNMENT_OPPOSED,
        )
        self.assertEqual(
            alignment_bucket_from_zone_and_trend(ZoneKind.SUPPLY, MarketTrend.BULLISH),
            ALIGNMENT_OPPOSED,
        )
        self.assertEqual(
            alignment_bucket_from_zone_and_trend(ZoneKind.DEMAND, MarketTrend.RANGING),
            ALIGNMENT_NEUTRAL,
        )
        self.assertEqual(
            alignment_bucket_from_zone_and_trend(None, MarketTrend.BULLISH),
            ALIGNMENT_NEUTRAL,
        )


class StructureContextExperimentTests(unittest.TestCase):
    def test_no_lookahead_uses_only_prefix(self) -> None:
        # Rising then falling series; late bars would flip structure if leaked.
        bars: list[Bar] = []
        price = 1.10
        for i in range(40):
            if i < 25:
                price += 0.0004
            else:
                price -= 0.0005
            bars.append(
                _bar(
                    i,
                    high=price + 0.0003,
                    low=price - 0.0003,
                    close=price,
                )
            )
        # Force a DEMAND zone "created" mid-uptrend.
        mid = 20
        auto = _synthetic_zone(
            zone_id=1,
            kind=ZoneKind.DEMAND,
            conf_index=mid,
            conf_time=bars[mid].timestamp,
        )
        ctx = classify_zone_structure_context(
            auto, bars, symbol="EURUSD", timeframe="M15"
        )
        # Recreate with only prefix — must match (determinism + no leak).
        ctx_prefix = classify_zone_structure_context(
            auto, bars[: mid + 1], symbol="EURUSD", timeframe="M15"
        )
        self.assertEqual(ctx.market_trend, ctx_prefix.market_trend)
        self.assertEqual(ctx.structure_bucket, ctx_prefix.structure_bucket)
        self.assertEqual(ctx.alignment_bucket, ctx_prefix.alignment_bucket)
        self.assertLessEqual(ctx.origin_confirmation_index, mid)

    def test_deterministic_classification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=12)
            a = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=True,
                include_geometry_lifecycle=False,
            )
            b = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=True,
                include_geometry_lifecycle=False,
            )
        self.assertIsNotNone(a.structure_context_experiment)
        self.assertEqual(
            a.structure_context_experiment["contexts"],
            b.structure_context_experiment["contexts"],
        )
        self.assertEqual(
            a.structure_context_experiment["aggregates"],
            b.structure_context_experiment["aggregates"],
        )

    def test_empty_insufficient_structure(self) -> None:
        # Very short series → UNKNOWN / neutral_unclear.
        bars = [_bar(i, high=1.101, low=1.099, close=1.100) for i in range(5)]
        auto = _synthetic_zone(
            zone_id=7,
            kind=ZoneKind.SUPPLY,
            conf_index=4,
            conf_time=bars[4].timestamp,
        )
        ctx = classify_zone_structure_context(
            auto, bars, symbol="EURUSD", timeframe="M15"
        )
        self.assertEqual(ctx.structure_bucket, STRUCTURE_NEUTRAL)
        self.assertEqual(ctx.alignment_bucket, ALIGNMENT_NEUTRAL)
        self.assertEqual(ctx.market_trend, MarketTrend.UNKNOWN.value)

        result = run_structure_context_on_zones(
            [auto],
            (),
            bars,
            symbol="EURUSD",
            timeframe="M15",
        )
        self.assertEqual(result.aggregates["by_structure"][STRUCTURE_NEUTRAL]["zone_count"], 1)
        self.assertTrue(
            result.aggregates["by_structure"][STRUCTURE_NEUTRAL]["sample_size"][
                "too_small_to_interpret"
            ]
        )

    def test_report_serialization_includes_structure_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m1.csv"
            _write_m1_csv(path, hours=10)
            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                include_segment_stability=False,
                include_structure_context=True,
                include_geometry_lifecycle=False,
            )
            payload = result.to_dict()
            out = Path(td) / "out.json"
            out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            loaded = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(loaded["pipeline_version"], PIPELINE_VERSION)
        self.assertIn("structure_context_experiment", loaded)
        sce = loaded["structure_context_experiment"]
        self.assertIsNotNone(sce)
        self.assertIn("aggregates", sce)
        self.assertIn("by_structure", sce["aggregates"])
        self.assertIn("by_alignment", sce["aggregates"])
        self.assertIn("diagnosis", sce)
        self.assertIn("sample_size", sce["aggregates"]["by_structure"]["bullish"])

    def test_chronological_third_structure_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Multi-day contiguous weekdays for thirds.
            path = Path(td) / "m1.csv"
            lines = ["time,open,high,low,close,volume"]
            px = 1.10
            day = datetime(2026, 1, 5, 0, 0, 0)
            days = 0
            while days < 9:
                if day.weekday() < 5:
                    for i in range(6 * 60):
                        ts = day + timedelta(minutes=i)
                        wave = 0.00015 * ((i % 17) - 8)
                        o = px
                        c = px + wave
                        h = max(o, c) + 0.00005
                        l = min(o, c) - 0.00005
                        lines.append(
                            f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')},"
                            f"{o:.5f},{h:.5f},{l:.5f},{c:.5f},{days * 1000 + i + 1}"
                        )
                        px = c
                    days += 1
                day += timedelta(days=1)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 15),
                timeframes=("M15",),
                include_segment_stability=True,
                include_structure_context=True,
                include_geometry_lifecycle=False,
            )

        self.assertEqual(result.segment_stability["segment_count"], 3)
        for seg in result.segment_stability["segments"]:
            self.assertIn("structure_context_experiment", seg)
            sce = seg["structure_context_experiment"]
            self.assertIn("aggregates", sce)
            self.assertIn("by_alignment", sce["aggregates"])
        self.assertIn(
            "structure_alignment_stability",
            result.segment_stability,
        )

    def test_alignment_classification_with_real_generator(self) -> None:
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
                include_structure_context=True,
                include_geometry_lifecycle=False,
            )
        sce = result.structure_context_experiment
        assert sce is not None
        for ctx in sce["contexts"]:
            trend = MarketTrend(ctx["market_trend"])
            kind = None if ctx["zone_kind"] is None else ZoneKind(ctx["zone_kind"])
            expected = alignment_bucket_from_zone_and_trend(kind, trend)
            self.assertEqual(ctx["alignment_bucket"], expected)
            self.assertEqual(
                ctx["structure_bucket"], structure_bucket_from_trend(trend)
            )


if __name__ == "__main__":
    unittest.main()
