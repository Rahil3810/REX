"""Breakout detection rule extracted from the core breakout strategy."""

from models.bar import Bar
from models.zone import Zone


class BreakoutRule:
    """
    Detect whether a candle has broken above or below a zone.

    This class intentionally contains only the breakout checks that previously
    lived inside BreakoutStrategy. It does not create signals, track state,
    detect zone entries, or decide close-outside events.
    """

    def detect_break_above(
        self,
        bar: Bar,
        zone: Zone,
        previous_position: str | None,
    ) -> bool:
        """Return True when the bar breaks above the zone."""
        if previous_position is None:
            return bar.close > zone.high and bar.low <= zone.high
        return previous_position != "above" and bar.close > zone.high

    def detect_break_below(
        self,
        bar: Bar,
        zone: Zone,
        previous_position: str | None,
    ) -> bool:
        """Return True when the bar breaks below the zone."""
        if previous_position is None:
            return bar.close < zone.low and bar.high >= zone.low
        return previous_position != "below" and bar.close < zone.low
