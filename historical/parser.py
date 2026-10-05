"""Strict CSV parsing into the project's existing Bar model."""

import csv
from pathlib import Path

from historical.bar_contract import rows_from_mapping
from historical.exceptions import HistoricalParseError
from models.bar import Bar


class HistoricalDataParser:
    """Parse and validate canonical or duka M1 CSV files into REX ``Bar``s.

    Dukascopy/duka timestamps without timezone are treated as UTC wall times
    (see ``historical.bar_contract``). No local-machine timezone is applied.
    """

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
                return rows_from_mapping(reader, symbol.upper())
        except OSError as exc:
            raise HistoricalParseError(f"Unable to read historical file: {path}") from exc
        except HistoricalParseError:
            raise
        except Exception as exc:  # defensive: csv DictReader edge cases
            raise HistoricalParseError(f"Unable to parse historical file: {path}: {exc}") from exc
