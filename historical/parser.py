"""Strict CSV parsing into the project's existing Bar model."""

import csv
import math
from datetime import datetime, timezone
from pathlib import Path

from historical.exceptions import HistoricalParseError
from models.bar import Bar


class HistoricalDataParser:
    """Parse and validate canonical or duka M1 CSV files."""

    _TIMESTAMP_COLUMNS = ("timestamp", "time")

    def parse_file(self, path: Path, symbol: str) -> list[Bar]:
        """Parse one CSV file into chronologically ordered bars.

        Args:
            path: Source CSV path.
            symbol: Symbol assigned to each parsed bar.

        Returns:
            Validated bars in file order.

        Raises:
            HistoricalParseError: If any row, ordering, or duplicate is invalid.
        """
        try:
            with path.open("r", encoding="utf-8", newline="") as source:
                first_line = source.readline()
                source.seek(0)
                has_header = any(
                    name in first_line.lower() for name in ("time", "open", "close")
                )
                reader = (
                    csv.DictReader(source)
                    if has_header
                    else csv.DictReader(
                        source,
                        delimiter=";",
                        fieldnames=(
                            "time",
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                        ),
                    )
                )
                return self._parse_rows(reader, symbol.upper())
        except OSError as exc:
            raise HistoricalParseError(f"Unable to read historical file: {path}") from exc

    def _parse_rows(self, rows: csv.DictReader[str], symbol: str) -> list[Bar]:
        bars: list[Bar] = []
        previous: datetime | None = None
        seen: set[datetime] = set()
        for row_number, row in enumerate(rows, start=2):
            try:
                timestamp_text = next(
                    row[name]
                    for name in self._TIMESTAMP_COLUMNS
                    if name in row and row[name]
                )
                timestamp = self._timestamp(timestamp_text)
                values = {
                    name: self._price(row.get(name), name)
                    for name in ("open", "high", "low", "close")
                }
                volume_text = row.get("volume")
                volume = (
                    None
                    if volume_text is None or not volume_text.strip()
                    else self._price(volume_text, "volume", allow_zero=True)
                )
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                raise HistoricalParseError(
                    f"Invalid historical row {row_number}: {exc}"
                ) from exc

            if values["high"] < values["low"]:
                raise HistoricalParseError(f"Invalid row {row_number}: high below low")
            if not values["low"] <= values["open"] <= values["high"]:
                raise HistoricalParseError(f"Invalid row {row_number}: open outside range")
            if not values["low"] <= values["close"] <= values["high"]:
                raise HistoricalParseError(f"Invalid row {row_number}: close outside range")
            if timestamp in seen:
                raise HistoricalParseError(
                    f"Duplicate timestamp at row {row_number}: {timestamp.isoformat()}"
                )
            if previous is not None and timestamp <= previous:
                raise HistoricalParseError(
                    f"Out-of-order timestamp at row {row_number}: {timestamp.isoformat()}"
                )
            seen.add(timestamp)
            previous = timestamp
            bars.append(Bar(symbol, timestamp, volume=volume, **values))
        return bars

    @staticmethod
    def _timestamp(value: str) -> datetime:
        text = value.strip()

        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.strptime(text, "%Y%m%d %H%M%S")

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

        return parsed

    @staticmethod
    def _price(value: str | None, name: str, allow_zero: bool = False) -> float:
        if value is None or not value.strip():
            raise ValueError(f"missing {name}")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0 or (parsed == 0 and not allow_zero):
            raise ValueError(f"invalid {name}")
        return parsed
