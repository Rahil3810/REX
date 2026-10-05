"""Tests for Dukascopy adapter → canonical bars → storage → FeatureRepository."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core.features import FeatureRepository, PACK_PRICE, PACK_STRUCTURE
from core.features.generators.bos import detect_swing_bos
from core.features.packs.base import StructurePack
from historical.bar_contract import (
    assess_dataset_quality,
    build_canonical_bar,
    normalize_provider_timestamp,
)
from historical.config import load_historical_config
from historical.downloader import HistoricalDownloader
from historical.exceptions import HistoricalDownloadError, HistoricalParseError
from historical.provider import HistoricalDataProvider
from historical.sources import DukascopyAdapter
from historical.storage import HistoricalStorage
from models.bar import Bar


class FakeDukaRunner:
    """Fixture runner — never touches the network."""

    def __init__(self, content: str | None = None, fail_times: int = 0) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.content = content or (
            "time,open,close,high,low,volume\n"
            "2024-01-02 00:00:00.000000,1.10,1.11,1.12,1.09,10\n"
            "2024-01-02 00:01:00.000000,1.11,1.12,1.13,1.10,11\n"
            "2024-01-02 00:02:00.000000,1.12,1.11,1.14,1.10,12\n"
        )
        self.last_args: dict[str, object] = {}

    def download(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        destination: Path,
        timeout_seconds: float,
        threads: int,
        include_header: bool,
    ) -> Path:
        self.calls += 1
        self.last_args = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "timeframe": timeframe,
        }
        if self.calls <= self.fail_times:
            raise RuntimeError("temporary duka failure")
        path = destination / "duka.csv"
        path.write_text(self.content, encoding="utf-8")
        return path


class BarContractTests(unittest.TestCase):
    def test_provider_to_canonical_bar_conversion(self) -> None:
        bar = build_canonical_bar(
            symbol="eurusd",
            timestamp="2024-01-02T00:00:00Z",
            open="1.10",
            high="1.12",
            low="1.09",
            close="1.11",
            volume="5",
        )
        self.assertEqual(bar.symbol, "EURUSD")
        self.assertEqual(bar.timestamp, datetime(2024, 1, 2, 0, 0, 0))
        self.assertIsNone(bar.timestamp.tzinfo)
        self.assertEqual(bar.open, 1.10)
        self.assertEqual(bar.high, 1.12)
        self.assertEqual(bar.low, 1.09)
        self.assertEqual(bar.close, 1.11)
        self.assertEqual(bar.volume, 5.0)

    def test_timestamp_normalization_utc_and_equivalent_offsets(self) -> None:
        naive = normalize_provider_timestamp("2024-06-01 12:00:00")
        zulu = normalize_provider_timestamp("2024-06-01T12:00:00Z")
        offset = normalize_provider_timestamp("2024-06-01T14:00:00+02:00")
        aware = normalize_provider_timestamp(
            datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(naive, datetime(2024, 6, 1, 12, 0, 0))
        self.assertEqual(zulu, naive)
        self.assertEqual(offset, naive)
        self.assertEqual(aware, naive)
        self.assertIsNone(naive.tzinfo)

    def test_dst_boundary_offset_converts_to_utc_wall_time(self) -> None:
        # US Eastern spring-forward 2024-03-10 02:00 does not exist locally;
        # an explicit +00:00 / offset input must still normalize to UTC wall time.
        before = normalize_provider_timestamp("2024-03-10T06:59:00+00:00")
        after = normalize_provider_timestamp("2024-03-10T07:00:00+00:00")
        self.assertEqual(before, datetime(2024, 3, 10, 6, 59))
        self.assertEqual(after, datetime(2024, 3, 10, 7, 0))
        self.assertLess(before, after)

    def test_rejects_invalid_ohlc_and_does_not_coerce_zero(self) -> None:
        with self.assertRaises(HistoricalParseError):
            build_canonical_bar(
                symbol="EURUSD",
                timestamp="2024-01-01 00:00:00",
                open=1.0,
                high=0.5,
                low=2.0,
                close=1.0,
            )
        with self.assertRaises(HistoricalParseError):
            build_canonical_bar(
                symbol="EURUSD",
                timestamp="2024-01-01 00:00:00",
                open=0.0,
                high=1.0,
                low=0.5,
                close=0.8,
            )
        with self.assertRaises(HistoricalParseError):
            build_canonical_bar(
                symbol="EURUSD",
                timestamp="2024-01-01 00:00:00",
                open=float("nan"),
                high=1.0,
                low=0.5,
                close=0.8,
            )

    def test_rejects_missing_fields(self) -> None:
        with self.assertRaises(HistoricalParseError):
            build_canonical_bar(
                symbol="EURUSD",
                timestamp="2024-01-01 00:00:00",
                open="",
                high=1.0,
                low=0.5,
                close=0.8,
            )


class DukascopyAdapterTests(unittest.TestCase):
    def test_fetch_maps_provider_csv_to_ordered_bars(self) -> None:
        adapter = DukascopyAdapter(runner=FakeDukaRunner())
        bars = adapter.fetch_bars("EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 2))
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0].timestamp, datetime(2024, 1, 2, 0, 0))
        self.assertEqual(bars[1].timestamp.minute, 1)
        self.assertTrue(all(b.timestamp.tzinfo is None for b in bars))
        self.assertEqual(adapter.provider_id, "dukascopy")

    def test_rejects_duplicate_and_out_of_order_provider_rows(self) -> None:
        dup = FakeDukaRunner(
            "time,open,close,high,low\n"
            "2024-01-02 00:00:00.000000,1.10,1.11,1.12,1.09\n"
            "2024-01-02 00:00:00.000000,1.10,1.11,1.12,1.09\n"
        )
        with self.assertRaises(HistoricalParseError):
            DukascopyAdapter(runner=dup).fetch_bars(
                "EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 2)
            )

    def test_provider_failure_surfaces_as_download_error(self) -> None:
        runner = FakeDukaRunner(fail_times=99)
        with self.assertRaises(HistoricalDownloadError):
            DukascopyAdapter(runner=runner).fetch_bars(
                "EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 2)
            )

    def test_inclusive_date_bounds_passed_to_runner(self) -> None:
        runner = FakeDukaRunner()
        DukascopyAdapter(runner=runner).fetch_bars(
            "EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 3)
        )
        self.assertEqual(runner.last_args["start_date"], date(2024, 1, 2))
        self.assertEqual(runner.last_args["end_date"], date(2024, 1, 3))


class StorageIngestionTests(unittest.TestCase):
    def test_adapter_to_storage_metadata_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                load_historical_config(),
                symbols=("EURUSD",),
                data_directory=Path(directory),
                retries=0,
                overwrite_existing_files=True,
            )
            runner = FakeDukaRunner()
            paths = HistoricalDownloader(config, runner=runner).download(
                start_date=date(2024, 1, 2), end_date=date(2024, 1, 2)
            )
            path = paths[0]
            self.assertTrue(path.exists())
            meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["provider"], "dukascopy")
            self.assertEqual(meta["bar_count"], 3)
            self.assertEqual(meta["start_date"], "2024-01-02")
            self.assertEqual(meta["end_date"], "2024-01-02")
            storage = HistoricalStorage(Path(directory))
            self.assertTrue(
                storage.has_coverage(
                    "EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 2)
                )
            )

    def test_repeated_ingestion_is_deterministic_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                load_historical_config(),
                symbols=("EURUSD",),
                data_directory=Path(directory),
                retries=0,
                overwrite_existing_files=True,
            )
            runner = FakeDukaRunner()
            downloader = HistoricalDownloader(config, runner=runner)
            downloader.download(start_date=date(2024, 1, 2), end_date=date(2024, 1, 2))
            first = (Path(directory) / "EURUSD" / "M1" / "2024.csv").read_text(
                encoding="utf-8"
            )
            downloader.download(start_date=date(2024, 1, 2), end_date=date(2024, 1, 2))
            second = (Path(directory) / "EURUSD" / "M1" / "2024.csv").read_text(
                encoding="utf-8"
            )
            self.assertEqual(first, second)
            self.assertEqual(runner.calls, 2)

    def test_quality_report_fields(self) -> None:
        bars = [
            Bar("EURUSD", datetime(2024, 1, 2, 0, 0), 1.1, 1.2, 1.0, 1.15, 1.0),
            Bar("EURUSD", datetime(2024, 1, 2, 0, 1), 1.15, 1.25, 1.1, 1.2, 1.0),
            Bar("EURUSD", datetime(2024, 1, 2, 0, 5), 1.2, 1.3, 1.15, 1.22, 1.0),
        ]
        report = assess_dataset_quality(
            bars,
            instrument="EURUSD",
            timeframe="M1",
            provider="dukascopy",
            coverage_start=date(2024, 1, 2),
            coverage_end=date(2024, 1, 2),
        )
        self.assertEqual(report.bar_count, 3)
        self.assertEqual(report.duplicate_count, 0)
        self.assertEqual(report.invalid_bar_count, 0)
        self.assertEqual(report.timestamp_gap_count, 1)
        self.assertEqual(report.provider, "dukascopy")
        self.assertEqual(report.first_timestamp, bars[0].timestamp)
        payload = report.to_dict()
        self.assertEqual(payload["coverage_start"], "2024-01-02")


class EndToEndFeatureRepositoryTests(unittest.TestCase):
    def test_feature_repository_consumes_ingested_dukascopy_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = replace(
                load_historical_config(),
                symbols=("EURUSD",),
                data_directory=Path(directory),
                retries=0,
                overwrite_existing_files=True,
            )
            # Longer fixture so structure pack has enough M1 bars
            lines = ["time,open,close,high,low,volume"]
            start = datetime(2024, 1, 2, 0, 0, 0)
            price = 1.1000
            for i in range(40):
                ts = start + timedelta(minutes=i)
                o = price
                h = price + 0.0005
                l = price - 0.0005
                c = price + 0.0001
                lines.append(
                    f"{ts.isoformat(sep=' ')}.000000,{o},{c},{h},{l},1"
                )
                price = c
            runner = FakeDukaRunner("\n".join(lines) + "\n")
            HistoricalDownloader(config, runner=runner).download(
                start_date=date(2024, 1, 2), end_date=date(2024, 1, 2)
            )
            bars = HistoricalDataProvider(config).get_bars(
                "EURUSD", "M1", date(2024, 1, 2), date(2024, 1, 2)
            )
            self.assertEqual(len(bars), 40)
            asof = bars[-1].timestamp
            context = FeatureRepository().materialize(
                "EURUSD",
                {"M1": bars},
                entry_timeframe="M1",
                pack_ids=(PACK_PRICE, PACK_STRUCTURE),
                asof=asof,
            )
            structure = context.require_pack(PACK_STRUCTURE, StructurePack)
            self.assertIn("M1", structure.swings.by_timeframe)
            # swing BOS still callable on ingested bars (no regression smoke)
            series = detect_swing_bos(bars, structure.swings.by_timeframe["M1"].swings)
            self.assertEqual(series.method_id, "swing_bos_v1")


class SmokeConfigTests(unittest.TestCase):
    def test_smoke_config_loads_small_interval(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_historical_config(root / "config" / "historical_data_smoke.json")
        self.assertEqual(config.provider, "dukascopy")
        self.assertEqual(config.symbols, ("EURUSD",))
        self.assertEqual(config.start_date, date(2024, 1, 2))
        self.assertEqual(config.end_date, date(2024, 1, 2))
        self.assertEqual(config.timeframe, "M1")


if __name__ == "__main__":
    unittest.main()
