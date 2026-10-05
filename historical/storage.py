"""Deterministic yearly CSV storage for historical bars."""

import csv
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from historical.exceptions import HistoricalStorageError
from models.bar import Bar


class HistoricalStorage:
    """Manage canonical ``symbol/timeframe/year.csv`` storage."""

    _FIELDS = ("timestamp", "open", "high", "low", "close", "volume")

    def __init__(self, data_directory: Path) -> None:
        """Initialize storage.

        Args:
            data_directory: Root directory containing symbol partitions.
        """
        self.data_directory = data_directory

    def year_path(self, symbol: str, timeframe: str, year: int) -> Path:
        """Return the canonical path for a yearly partition.

        Args:
            symbol: Market symbol.
            timeframe: Candle timeframe.
            year: Four-digit calendar year.

        Returns:
            Path to the yearly CSV file.
        """
        return self.data_directory / symbol.upper() / timeframe.upper() / f"{year}.csv"

    def has_coverage(
        self,
        symbol: str,
        timeframe: str,
        start_date: date,
        end_date: date,
    ) -> bool:
        """Check whether stored partitions cover a requested date range.

        Args:
            symbol: Market symbol.
            timeframe: Candle timeframe.
            start_date: Inclusive requested start date.
            end_date: Inclusive requested end date.

        Returns:
            ``True`` only when every calendar-year segment of the requested
            range has a non-empty CSV partition **and** valid ``.meta.json``
            coverage that includes that segment. Missing, unreadable, or
            incomplete metadata yields ``False`` (fail closed).
        """
        if start_date > end_date:
            return False

        for year in range(start_date.year, end_date.year + 1):
            segment_start = max(start_date, date(year, 1, 1))
            segment_end = min(end_date, date(year, 12, 31))
            path = self.year_path(symbol, timeframe, year)
            if not path.is_file() or path.stat().st_size == 0:
                return False
            coverage = self.coverage(symbol, timeframe, year)
            if coverage is None:
                return False
            coverage_start, coverage_end = coverage
            if coverage_start > coverage_end:
                return False
            if coverage_start > segment_start or coverage_end < segment_end:
                return False
        return True

    def coverage(
        self, symbol: str, timeframe: str, year: int
    ) -> tuple[date, date] | None:
        """Read recorded coverage for a yearly partition.

        Args:
            symbol: Market symbol.
            timeframe: Candle timeframe.
            year: Calendar partition year.

        Returns:
            Inclusive coverage dates from ``.meta.json``, or ``None`` when
            metadata is missing, unreadable, or malformed.
        """
        metadata = self._metadata_path(self.year_path(symbol, timeframe, year))
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            return (
                date.fromisoformat(payload["start_date"]),
                date.fromisoformat(payload["end_date"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def write_year(
        self,
        symbol: str,
        timeframe: str,
        year: int,
        bars: Iterable[Bar],
        coverage_start: date,
        coverage_end: date,
        *,
        provider: str | None = None,
        bar_count: int | None = None,
    ) -> Path:
        """Atomically write a yearly candle partition and coverage metadata.

        Args:
            symbol: Market symbol.
            timeframe: Candle timeframe.
            year: Calendar partition year.
            bars: Validated bars to persist.
            coverage_start: Inclusive downloaded coverage start.
            coverage_end: Inclusive downloaded coverage end.
            provider: Optional remote provider id recorded in metadata.
            bar_count: Optional bar count recorded in metadata.

        Returns:
            Final CSV path.

        Raises:
            HistoricalStorageError: If persistence fails.
        """
        path = self.year_path(symbol, timeframe, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(bars, key=lambda bar: bar.timestamp)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", newline="", dir=path.parent, delete=False
            ) as temporary:
                temporary_name = temporary.name
                writer = csv.DictWriter(temporary, fieldnames=self._FIELDS)
                writer.writeheader()
                for bar in ordered:
                    writer.writerow(
                        {
                            "timestamp": bar.timestamp.isoformat(sep=" "),
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": "" if bar.volume is None else bar.volume,
                        }
                    )
                temporary.flush()
                os.fsync(temporary.fileno())
            Path(temporary_name).replace(path)
            metadata: dict[str, object] = {
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "year": year,
                "start_date": coverage_start.isoformat(),
                "end_date": coverage_end.isoformat(),
            }
            if provider is not None:
                metadata["provider"] = provider
            metadata["bar_count"] = (
                len(ordered) if bar_count is None else int(bar_count)
            )
            self._metadata_path(path).write_text(
                json.dumps(metadata, indent=2),
                encoding="utf-8",
            )
            return path
        except OSError as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise HistoricalStorageError(f"Unable to write historical file: {path}") from exc

    def existing_files(
        self, symbol: str, timeframe: str, start_year: int, end_year: int
    ) -> tuple[Path, ...]:
        """Return existing yearly files in chronological order.

        Args:
            symbol: Market symbol.
            timeframe: Candle timeframe.
            start_year: First calendar year.
            end_year: Last calendar year.

        Returns:
            Existing partition paths ordered by year.
        """
        return tuple(
            path
            for year in range(start_year, end_year + 1)
            if (path := self.year_path(symbol, timeframe, year)).is_file()
        )

    @staticmethod
    def _metadata_path(path: Path) -> Path:
        return path.with_suffix(".meta.json")
