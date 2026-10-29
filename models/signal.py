"""Trading signal models."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SignalType(StrEnum):
    """Types of breakout-related signals emitted by the strategy."""

    ENTER_ZONE = "enter_zone"
    BREAK_ABOVE = "break_above"
    BREAK_BELOW = "break_below"
    CLOSE_OUTSIDE = "close_outside"
    BULLISH_SWEEP = "bullish_sweep"
    BEARISH_SWEEP = "bearish_sweep"
    RETEST_ABOVE = "retest_above"
    RETEST_BELOW = "retest_below"


@dataclass(frozen=True)
class Signal:
    """Structured signal produced when price interacts with a zone."""

    symbol: str
    signal: SignalType
    zone_id: int
    price: float
    timestamp: datetime
    reason: str
    nearest_zone_above: int | None = None
    nearest_zone_below: int | None = None
    distance_to_zone_above: float | None = None
    distance_to_zone_below: float | None = None
    market_context_summary: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Return the canonical signal format for logging and downstream integrations."""
        payload: dict[str, str] = {
            "symbol": self.symbol,
            "signal": self.signal.value,
            "zone_id": str(self.zone_id),
            "price": str(self.price),
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
        }

        if self.nearest_zone_above is not None:
            payload["nearest_zone_above"] = str(self.nearest_zone_above)
        if self.nearest_zone_below is not None:
            payload["nearest_zone_below"] = str(self.nearest_zone_below)
        if self.distance_to_zone_above is not None:
            payload["distance_to_zone_above"] = str(
                round(self.distance_to_zone_above, 1)
            )
        if self.distance_to_zone_below is not None:
            payload["distance_to_zone_below"] = str(
                round(self.distance_to_zone_below, 1)
            )
        if self.market_context_summary is not None:
            payload["market_context_summary"] = self.market_context_summary

        return payload

    @property
    def is_enriched(self) -> bool:
        """Return True when market context fields have been populated."""
        return self.market_context_summary is not None
