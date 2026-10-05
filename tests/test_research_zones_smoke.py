"""Integration tests for research Automatic Zone V1 smoke pipeline."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from research.zones_pipeline import (
    CLASSIFICATION_INSUFFICIENT,
    PIPELINE_VERSION,
    classify_research_result,
    compute_deterministic_hash,
    discover_dataset_bounds,
    resolve_evaluation_window,
    run_research_zones_smoke,
    run_timeframe_pipeline,
    split_date_range_into_thirds,
)


def _write_m1_csv(
    path: Path,
    *,
    start: datetime,
    n_minutes: int,
    base: float = 1.1000,
) -> None:
    """Write contiguous M1 OHLC that passes free-OHLC validation."""
    lines = ["time,open,high,low,close,volume"]
    px = base
    for i in range(n_minutes):
        ts = start + timedelta(minutes=i)
        wave = 0.00015 * ((i % 17) - 8)
        o = px
        c = px + wave
        h = max(o, c) + 0.00005
        l = min(o, c) - 0.00005
        lines.append(
            f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')},"
            f"{o:.5f},{h:.5f},{l:.5f},{c:.5f},{i + 1}"
        )
        px = c
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _monday_session_csv(tmp: Path, hours: int = 12) -> Path:
    """Monday UTC session long enough for M15 + H1 complete buckets."""
    path = tmp / "EURUSD_1m.csv"
    _write_m1_csv(path, start=datetime(2026, 1, 5, 0, 0, 0), n_minutes=hours * 60)
    return path


def _multi_day_csv(tmp: Path, days: int = 9, hours_per_day: int = 8) -> Path:
    """Write several weekdays of M1 (skipping weekends for cleaner HTF)."""
    path = tmp / "EURUSD_1m.csv"
    lines = ["time,open,high,low,close,volume"]
    px = 1.1000
    day = datetime(2026, 1, 5, 0, 0, 0)  # Monday
    written_days = 0
    while written_days < days:
        if day.weekday() < 5:
            for i in range(hours_per_day * 60):
                ts = day + timedelta(minutes=i)
                wave = 0.00015 * ((i % 17) - 8)
                o = px
                c = px + wave
                h = max(o, c) + 0.00005
                l = min(o, c) - 0.00005
                lines.append(
                    f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')},"
                    f"{o:.5f},{h:.5f},{l:.5f},{c:.5f},{written_days * 1000 + i + 1}"
                )
                px = c
            written_days += 1
        day += timedelta(days=1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ResearchZonesSmokeTests(unittest.TestCase):
    def test_m15_pipeline_produces_report_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=8)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15",),
                skip_invalid_ohlc=True,
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        self.assertIn("M15", result.by_timeframe)
        m15 = result.by_timeframe["M15"]
        self.assertGreater(m15.bar_count, 0)
        report = m15.report
        for key in (
            "source_dataset",
            "timeframe",
            "dataset_start",
            "dataset_end",
            "accepted_m1_bars",
            "dropped_invalid_bars",
            "resampled_bar_count",
            "incomplete_bucket_count",
            "bar_count",
            "swing_count",
            "automatic_zone_count",
            "supply_count",
            "demand_count",
            "zone_ids",
            "zones",
            "interaction_count",
            "SUCCESS_count",
            "FAILURE_count",
            "BROKEN_count",
            "UNAVAILABLE_count",
            "success_rate",
            "failure_rate",
            "broken_rate",
            "zone_generation_rate_per_bar",
            "interactions_per_zone",
            "zones_with_zero_interactions",
            "zones_with_multiple_interactions",
            "average_touches",
            "median_touches",
            "zone_width_distribution",
            "zone_strength_distribution",
            "mfe_statistics",
            "mae_statistics",
            "evaluation_configuration",
            "provenance",
            "research_summary",
            "volume",
        ):
            self.assertIn(key, report)
        self.assertEqual(report["timeframe"], "M15")
        self.assertEqual(report["provenance"]["pipeline_version"], PIPELINE_VERSION)
        self.assertEqual(report["volume"]["volume_type"], "tick_volume")

    def test_h1_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=12)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("H1",),
                skip_invalid_ohlc=True,
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        h1 = result.by_timeframe["H1"]
        self.assertGreater(h1.bar_count, 0)
        self.assertEqual(h1.report["timeframe"], "H1")

    def test_multi_timeframe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=12)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15", "H1", "H4", "D1"),
                skip_invalid_ohlc=True,
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        for tf in ("M15", "H1", "H4", "D1"):
            self.assertIn(tf, result.by_timeframe)
        self.assertGreater(result.by_timeframe["M15"].bar_count, 0)
        self.assertGreater(result.by_timeframe["H1"].bar_count, 0)
        # Strict completeness: H4/D1 may be empty on a single short day.
        self.assertEqual(result.by_timeframe["H4"].report["zone_count"], len(result.by_timeframe["H4"].zones))
        self.assertEqual(result.by_timeframe["D1"].bar_count, 0)

    def test_dataset_bound_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=3)
            bounds = discover_dataset_bounds(csv_path, symbol="EURUSD")
            self.assertEqual(bounds.first_date, date(2026, 1, 5))
            self.assertEqual(bounds.last_date, date(2026, 1, 5))
            self.assertGreater(bounds.accepted_m1_bars, 0)
            self.assertEqual(bounds.volume_type, "tick_volume")

            _, eff_start, eff_end = resolve_evaluation_window(
                csv_path, symbol="EURUSD", start=None, end=None
            )
            self.assertEqual(eff_start, date(2026, 1, 5))
            self.assertEqual(eff_end, date(2026, 1, 5))

            _, ov_start, ov_end = resolve_evaluation_window(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
            )
            self.assertEqual(ov_start, date(2026, 1, 5))
            self.assertEqual(ov_end, date(2026, 1, 5))

    def test_cli_start_end_override_uses_requested_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _multi_day_csv(Path(td), days=5, hours_per_day=6)
            # Override to first day only.
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15", "H1"),
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        self.assertEqual(result.requested_start, "2026-01-05")
        self.assertEqual(result.requested_end, "2026-01-05")
        self.assertEqual(result.effective_start, "2026-01-05")
        self.assertEqual(result.effective_end, "2026-01-05")
        self.assertEqual(
            result.by_timeframe["M15"].report["dataset_start"], "2026-01-05"
        )
        self.assertEqual(
            result.by_timeframe["M15"].report["dataset_end"], "2026-01-05"
        )

    def test_dataset_bounds_when_start_end_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _multi_day_csv(Path(td), days=3, hours_per_day=4)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=None,
                end=None,
                timeframes=("M15",),
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        self.assertIsNone(result.requested_start)
        self.assertIsNone(result.requested_end)
        self.assertEqual(result.effective_start, "2026-01-05")
        self.assertEqual(result.effective_end, "2026-01-07")

    def test_segment_statistics(self) -> None:
        segments = split_date_range_into_thirds(date(2026, 1, 5), date(2026, 1, 13))
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0][0], "first_third")
        self.assertEqual(segments[0][1], date(2026, 1, 5))
        self.assertEqual(segments[-1][0], "final_third")
        self.assertEqual(segments[-1][2], date(2026, 1, 13))

        with tempfile.TemporaryDirectory() as td:
            csv_path = _multi_day_csv(Path(td), days=9, hours_per_day=4)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 15),
                timeframes=("M15", "H1"),
                include_segment_stability=True,
                include_geometry_lifecycle=False,
            )
        self.assertEqual(result.segment_stability["segment_count"], 3)
        labels = [s["label"] for s in result.segment_stability["segments"]]
        self.assertEqual(labels, ["first_third", "middle_third", "final_third"])
        self.assertIn("M15", result.segment_stability["comparison"])
        for key in (
            "zone_counts",
            "success_rates",
            "broken_rates",
            "interactions_per_zone",
            "median_mfe",
            "median_mae",
            "median_zone_width",
        ):
            self.assertIn(key, result.segment_stability["comparison"]["M15"])

    def test_deterministic_repeated_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=10)
            kwargs = dict(
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15", "H1"),
                skip_invalid_ohlc=True,
                include_segment_stability=True,
                include_geometry_lifecycle=False,
            )
            a = run_research_zones_smoke(csv_path, **kwargs)
            b = run_research_zones_smoke(csv_path, **kwargs)

        self.assertEqual(a.summary["zones_generated"], b.summary["zones_generated"])
        self.assertEqual(a.deterministic_hash, b.deterministic_hash)
        self.assertEqual(
            compute_deterministic_hash(a.to_dict()),
            compute_deterministic_hash(b.to_dict()),
        )
        for tf in ("M15", "H1"):
            za = [z.to_dict() for z in a.by_timeframe[tf].zones]
            zb = [z.to_dict() for z in b.by_timeframe[tf].zones]
            self.assertEqual(za, zb)

    def test_no_future_leakage(self) -> None:
        from research.free_ohlc import build_research_dataset

        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=10)
            ds = build_research_dataset(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                skip_invalid_ohlc=True,
                target_timeframes=("M15",),
            )
            m15 = ds.bars("M15")
            self.assertGreater(len(m15), 10)
            asof = len(m15) // 2
            zones, evaluations, _ = run_timeframe_pipeline(
                m15,
                timeframe="M15",
                symbol="EURUSD",
                asof_index=asof,
            )
            asof_time = m15[asof].timestamp
            for auto in zones:
                self.assertLessEqual(auto.evidence.origin_confirmation_index, asof)
                self.assertLessEqual(auto.evidence.origin_confirmation_time, asof_time)
                self.assertEqual(auto.evidence.asof_index, asof)
            for ev in evaluations:
                self.assertLessEqual(ev.evaluated_at, asof_time)
                for interaction in ev.interactions:
                    self.assertLessEqual(interaction.entry_index, asof)
                    if interaction.exit_index is not None:
                        self.assertLessEqual(interaction.exit_index, asof)

    def test_empty_insufficient_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.csv"
            path.write_text("time,open,high,low,close,volume\n", encoding="utf-8")
            result = run_research_zones_smoke(
                path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15", "H1", "H4", "D1"),
                skip_invalid_ohlc=True,
                include_segment_stability=False,
                include_geometry_lifecycle=False,
            )
        self.assertEqual(result.summary["zones_generated"], 0)
        self.assertEqual(result.by_timeframe["M15"].bar_count, 0)
        self.assertEqual(result.by_timeframe["H1"].bar_count, 0)
        self.assertEqual(result.research_classification, CLASSIFICATION_INSUFFICIENT)

        # Synthetic classify path for empty M15
        label, _ = classify_research_result(
            by_timeframe=result.by_timeframe,
            segment_stability={"comparison": {}},
        )
        self.assertEqual(label, CLASSIFICATION_INSUFFICIENT)

    def test_report_serialization(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv_path = _monday_session_csv(Path(td), hours=8)
            result = run_research_zones_smoke(
                csv_path,
                symbol="EURUSD",
                start=date(2026, 1, 5),
                end=date(2026, 1, 5),
                timeframes=("M15", "H1"),
                skip_invalid_ohlc=True,
                include_segment_stability=True,
                include_geometry_lifecycle=False,
            )
            out = Path(td) / "report.json"
            payload = result.to_dict()
            out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            loaded = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(loaded["pipeline_version"], PIPELINE_VERSION)
        self.assertIn("timeframes", loaded)
        self.assertIn("summary", loaded)
        self.assertIn("provenance", loaded)
        self.assertIn("segment_stability", loaded)
        self.assertIn("research_classification", loaded)
        self.assertIn("deterministic_hash", loaded)
        self.assertTrue(loaded["deterministic_hash"])
        self.assertIn("M15", loaded["timeframes"])
        self.assertIn("H1", loaded["timeframes"])
        self.assertIsInstance(loaded["summary"]["zones_generated"], int)


if __name__ == "__main__":
    unittest.main()
