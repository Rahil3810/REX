"""Trading calendar boundary — no exchange calendars implemented yet."""

from datetime import datetime
from typing import Protocol


class TradingCalendar(Protocol):
    """
    Architectural boundary for session / exchange calendars.

    Concrete exchange calendars are intentionally not implemented.
    Forex mega-session labeling remains in ``SessionManager``.
    """

    def is_trading(self, at: datetime) -> bool:
        """Return True when the market is considered open at ``at``."""


class AlwaysOpenCalendar:
    """Null calendar: always tradable. Useful for 24/7 domains and tests."""

    def is_trading(self, at: datetime) -> bool:
        return True
