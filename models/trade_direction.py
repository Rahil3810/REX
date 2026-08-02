"""Trade direction enumeration."""

from enum import StrEnum


class TradeDirection(StrEnum):
    """Side of a trade opportunity or position."""

    LONG = "LONG"
    SHORT = "SHORT"
