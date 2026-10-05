"""Provider-neutral access to locally stored historical market data.

This class reads from ``HistoricalStorage``. Remote Dukascopy fetching is
``DukascopyAdapter`` / ``HistoricalDownloader`` — not this type.
"""

from datetime import date, datetime, time

from historical.config import HistoricalDataConfig, load_historical_config
from historical.exceptions import UnsupportedHistoricalDataError
from historical.parser import HistoricalDataParser
from historical.storage import HistoricalStorage
from models.bar import Bar


class HistoricalDataProvider:
    """Read validated historical bars through a stable provider-neutral API."""

    def __init__(
        self,
        config: HistoricalDataConfig | None = None,
        storage: HistoricalStorage | None = None,
        parser: HistoricalDataParser | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            config: Historical settings, or ``None`` for the default JSON file.
            storage: Optional storage implementation for dependency injection.
            parser: Optional CSV parser for dependency injection.
        """
        self.config = config or load_historical_config()
        self.storage = storage or HistoricalStorage(self.config.data_directory)
        self.parser = parser or HistoricalDataParser()

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_date: date,
        end_date: date,
    ) -> list[Bar]:
        """Return bars inside an inclusive date range.

        Date bounds are inclusive calendar dates in UTC (naive bar timestamps
        are compared as UTC wall times). End-of-day uses ``time.max``.

        Args:
            symbol: Configured market symbol.
            timeframe: Requested candle timeframe; currently ``M1``.
            start_date: Inclusive start date.
            end_date: Inclusive end date.

        Returns:
            Validated bars ordered chronologically.

        Raises:
            UnsupportedHistoricalDataError: If the request is unsupported.
            ValueError: If the date range is reversed.
        """
        normalized_symbol = symbol.upper()
        normalized_timeframe = timeframe.upper()
        if normalized_symbol not in self.config.symbols:
            raise UnsupportedHistoricalDataError(
                f"Historical symbol is not configured: {normalized_symbol}"
            )
        if normalized_timeframe != self.config.timeframe:
            raise UnsupportedHistoricalDataError(
                f"Historical timeframe is not supported: {normalized_timeframe}"
            )
        if start_date > end_date:
            raise ValueError("start_date cannot be after end_date")

        lower = datetime.combine(start_date, time.min)
        upper = datetime.combine(end_date, time.max)
        bars: list[Bar] = []
        for path in self.storage.existing_files(
            normalized_symbol,
            normalized_timeframe,
            start_date.year,
            end_date.year,
        ):
            bars.extend(
                bar
                for bar in self.parser.parse_file(path, normalized_symbol)
                if lower <= bar.timestamp <= upper
            )
        return bars
