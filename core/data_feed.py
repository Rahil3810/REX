"""Provider-neutral live and replay data-feed abstractions."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from models.bar import Bar


class DataFeed(ABC):
    """
    Abstract data feed interface.

    Concrete implementations may connect to future live-data providers or
    replay stored data. This contract contains no provider-specific behavior.
    """

    @abstractmethod
    def subscribe(self, symbol: str, timeframe: str) -> None:
        """Subscribe to live or historical data for a symbol."""

    @abstractmethod
    def get_latest_bar(self, symbol: str) -> Bar | None:
        """Return the most recent completed bar for a symbol."""

    @abstractmethod
    def stream_bars(self, symbol: str) -> Iterator[Bar]:
        """Yield bars as they become available (live or replay)."""


class MockDataFeed(DataFeed):
    """
    In-memory data feed for development and testing.

    Accepts pre-loaded bars and yields them sequentially. Not intended for
    production use; replace it with a provider-specific DataFeed later.
    """

    def __init__(self, bars: dict[str, list[Bar]]) -> None:
        self._bars: dict[str, list[Bar]] = bars
        self._subscriptions: dict[str, str] = {}

    def subscribe(self, symbol: str, timeframe: str) -> None:
        self._subscriptions[symbol] = timeframe

    def get_latest_bar(self, symbol: str) -> Bar | None:
        symbol_bars = self._bars.get(symbol, [])
        return symbol_bars[-1] if symbol_bars else None

    def stream_bars(self, symbol: str) -> Iterator[Bar]:
        for bar in self._bars.get(symbol, []):
            yield bar
