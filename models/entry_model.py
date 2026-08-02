"""Entry model enumeration for planned and filled entries."""

from enum import StrEnum


class EntryModel(StrEnum):
    """How an entry is intended to be triggered."""

    NEXT_CANDLE_OPEN = "next_candle_open"
    LIMIT = "limit"
    STOP = "stop"
