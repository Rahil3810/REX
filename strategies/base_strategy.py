"""Common strategy contract used by research and backtesting."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from models.bar import Bar
from models.signal import Signal


class BaseStrategy(ABC):
    """Minimal interface every catalogued strategy must implement."""

    strategy_id: str
    strategy_name: str
    description: str

    @abstractmethod
    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        """
        Analyze historical candles and return generated signals.
        """


