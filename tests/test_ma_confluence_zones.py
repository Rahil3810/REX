"""Tests for MA Confluence Zone V1 (research, causal)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.indicators import IndicatorEngine, PandasTAProvider
from core.zones.auto.ma_confluence import (
    MAConfluenceStatus,
    MAConfluenceZoneConfig,
    MAConfluenceZoneGenerator,
    compute_zone_bounds,
    deterministic_ma_zone_id,
)
from models.bar import Bar
from models.zone import ZoneSource
from research.ma_confluence_pipeline import (
    MAConfluencePipelineResult,
    candidate_export_row,
    write_candidates_csv,
    write_candidates_json,
)


def _bar(
    i: int,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
    symbol: str = "EURUSD",
) -> Bar:
    h = close + 0.0003 if high is None else high
    l = close - 0.0003 if low is None else low
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 1, 5, 0, 0) + timedelta(hours=i),
        open=close,
        high=max(h, close),
        low=min(l, close),
        close=close,
        volume=10.0,
    )


def _flat_confluence_bars(n: int = 320) -> list[Bar]:
    """Long near-flat series: EMAs converge; ATR stays defined after warmup."""
    bars: list[Bar] = []
    px = 1.1000
    for i in range(n):
        # Tiny oscillation so ATR > 0 but EMA20≈EMA50 after warmup.
        wave = 0.00001 * ((i % 7) - 3)
        c = px + wave
        bars.append(
            _bar(
                i,
                close=c,
                high=c + 0.00015,
                low=c - 0.00015,
            )
        )
        px = 1.1000  # mean-revert to keep EMAs stacked
    return bars


def _trending_then_flat(n_trend: int = 250, n_flat: int = 40) -> list[Bar]:
    """Enough bars for EMA200 warmup, then a flat stretch for confluence."""
    return _flat_confluence_bars(n_trend + n_flat)

class ZoneBoundsTests(unittest.TestCase):
    def test_pads_when_cluster_narrower_than_floor(self) -> None:
        low, high = compute_zone_bounds(1.1000, 1.1001, 0.0010, min_width_atr=0.25)
        self.assertAlmostEqual(high - low, 0.00025)
        self.assertLess(low, 1.1000)
        self.assertGreater(high, 1.1001)

    def test_uses_ma_minmax_when_wider_than_floor(self) -> None:
        low, high = compute_zone_bounds(1.1000, 1.1010, 0.0010, min_width_atr=0.25)
        self.assertAlmostEqual(low, 1.1000)
        self.assertAlmostEqual(high, 1.1010)

    def test_deterministic_ids_stable(self) -> None:
        a = deterministic_ma_zone_id(
            timeframe="H1", created_index=10, low=1.1, high=1.2
        )
        b = deterministic_ma_zone_id(
            timeframe="H1", created_index=10, low=1.1, high=1.2
        )
        self.assertEqual(a, b)


class MAConfluenceGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MAConfluenceZoneConfig()
        self.engine = IndicatorEngine(PandasTAProvider())
        self.generator = MAConfluenceZoneGenerator(
            self.config, indicator_engine=self.engine
        )

    def test_empty_and_invalid_asof(self) -> None:
        self.assertEqual(
            self.generator.generate([], timeframe="H1", asof_index=0),
            (),
        )
        bars = _trending_then_flat()
        self.assertEqual(
            self.generator.generate(bars, timeframe="H1", asof_index=-1),
            (),
        )

    def test_no_lookahead_future_bars_do_not_change_past_asof(self) -> None:
        bars = _flat_confluence_bars()
        asof = len(bars) - 20
        before = self.generator.generate(bars, timeframe="H1", asof_index=asof)
        extended = list(bars) + [
            _bar(len(bars) + i, close=1.5 + i * 0.01) for i in range(30)
        ]
        after = self.generator.generate(extended, timeframe="H1", asof_index=asof)
        self.assertEqual(len(before), len(after))
        for a, b in zip(before, after, strict=True):
            self.assertEqual(a.zone.id, b.zone.id)
            self.assertAlmostEqual(a.zone.low, b.zone.low)
            self.assertAlmostEqual(a.zone.high, b.zone.high)
            self.assertEqual(a.evidence.created_index, b.evidence.created_index)

    def test_frozen_bounds_do_not_move_while_active(self) -> None:
        bars = _flat_confluence_bars()
        zones = self.generator.generate(
            bars, timeframe="H1", asof_index=len(bars) - 1
        )
        active = [z for z in zones if z.evidence.status == MAConfluenceStatus.ACTIVE]
        self.assertGreaterEqual(len(active), 1)
        z = active[0]
        at_create = self.generator.generate(
            bars, timeframe="H1", asof_index=z.evidence.created_index
        )
        match = next(x for x in at_create if x.zone.id == z.zone.id)
        self.assertAlmostEqual(match.zone.low, z.zone.low)
        self.assertAlmostEqual(match.zone.high, z.zone.high)

    def test_source_automatic_and_kind_none(self) -> None:
        bars = _flat_confluence_bars()
        zones = self.generator.generate(
            bars, timeframe="H1", asof_index=len(bars) - 1
        )
        self.assertGreaterEqual(len(zones), 1)
        for z in zones:
            self.assertEqual(z.zone.source, ZoneSource.AUTOMATIC)
            self.assertIsNone(z.zone.kind)
            self.assertLess(z.zone.low, z.zone.high)
            self.assertIsNotNone(z.evidence.convergence_start_index)
            self.assertLessEqual(
                z.evidence.convergence_start_index, z.evidence.created_index
            )

    def test_threshold_reject_when_k_enter_tiny(self) -> None:
        bars = _flat_confluence_bars()
        strict = MAConfluenceZoneGenerator(
            MAConfluenceZoneConfig(k_enter=0.0001, min_persist=3)
        )
        zones = strict.generate(bars, timeframe="H1", asof_index=len(bars) - 1)
        self.assertEqual(zones, ())

    def test_historical_snapshots_retained_after_expire(self) -> None:
        """Expired zones remain in the output (no retention cap)."""
        bars = _flat_confluence_bars(320)
        # Append strong trend to force divergence / expire.
        px = bars[-1].close
        for i in range(80):
            px += 0.0015
            bars.append(
                _bar(
                    len(bars),
                    close=px,
                    high=px + 0.0008,
                    low=px - 0.0002,
                )
            )
        zones = self.generator.generate(
            bars, timeframe="H1", asof_index=len(bars) - 1
        )
        expired = [
            z for z in zones if z.evidence.status == MAConfluenceStatus.EXPIRED
        ]
        self.assertGreaterEqual(len(zones), 1)
        for z in expired:
            self.assertIsNotNone(z.evidence.expired_index)
            self.assertIsNotNone(z.evidence.expired_time)

    def test_ema_matches_indicator_engine(self) -> None:
        bars = _flat_confluence_bars()
        asof = len(bars) - 1
        zones = self.generator.generate(bars, timeframe="H1", asof_index=asof)
        self.assertGreaterEqual(len(zones), 1)
        z = zones[0]
        prefix = bars[: z.evidence.created_index + 1]
        ema20 = float(self.engine.ema(prefix, length=20).iloc[-1])
        ema50 = float(self.engine.ema(prefix, length=50).iloc[-1])
        self.assertAlmostEqual(z.evidence.ema20, ema20, places=8)
        self.assertAlmostEqual(z.evidence.ema50, ema50, places=8)

    def test_deterministic_full_replay(self) -> None:
        bars = _flat_confluence_bars()
        a = self.generator.generate(bars, timeframe="H1", asof_index=len(bars) - 1)
        b = self.generator.generate(bars, timeframe="H1", asof_index=len(bars) - 1)
        self.assertGreaterEqual(len(a), 1)
        self.assertEqual([z.zone.id for z in a], [z.zone.id for z in b])
        self.assertEqual(
            [(z.zone.low, z.zone.high) for z in a],
            [(z.zone.low, z.zone.high) for z in b],
        )


class MAConfluenceExportTests(unittest.TestCase):
    def test_export_row_schema(self) -> None:
        bars = _flat_confluence_bars()
        gen = MAConfluenceZoneGenerator()
        zones = gen.generate(bars, timeframe="H1", asof_index=len(bars) - 1)
        self.assertGreaterEqual(len(zones), 1)
        row = candidate_export_row(
            zones[0], price_at_creation=bars[zones[0].evidence.created_index].close
        )
        required = {
            "zone_id",
            "symbol",
            "timeframe",
            "created_at",
            "low",
            "high",
            "EMA20",
            "EMA50",
            "EMA200",
            "ATR14",
            "separation",
            "separation_over_atr",
            "convergence_start",
            "convergence_duration",
            "status",
            "expired_at",
            "distance_from_price",
            "chart_hint",
        }
        self.assertTrue(required.issubset(row.keys()))

    def test_export_writers_json_and_csv(self) -> None:
        bars = _flat_confluence_bars()
        gen = MAConfluenceZoneGenerator()
        zones = gen.generate(bars, timeframe="H1", asof_index=len(bars) - 1)
        self.assertGreaterEqual(len(zones), 1)
        rows = tuple(
            candidate_export_row(
                z, price_at_creation=bars[z.evidence.created_index].close
            )
            for z in zones
        )
        result = MAConfluencePipelineResult(
            pipeline_version="test",
            source_path="synthetic",
            symbol="EURUSD",
            timeframe="H1",
            effective_start="2026-01-05",
            effective_end="2026-01-18",
            config=MAConfluenceZoneConfig().to_dict(),
            bar_count=len(bars),
            candidates=zones,
            export_rows=rows,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "out.json"
            out_csv = Path(tmp) / "out.csv"
            write_candidates_json(result, out_json)
            write_candidates_csv(result, out_csv)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_csv.exists())
            text = out_csv.read_text(encoding="utf-8")
            self.assertIn("convergence_start", text)
            self.assertIn("chart_hint", text)
            payload = result.to_dict()
            self.assertEqual(payload["config"]["k_enter"], 0.30)
            self.assertIn("research_questions", payload)