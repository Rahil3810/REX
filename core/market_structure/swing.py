"""
Strategy V1 market-structure contracts.

These interfaces are intentionally unimplemented. The existing research
``MarketStructureAnalyzer`` / ``TrendAnalyzer`` path is unchanged and remains
the current analysis implementation. Strategy V1 should depend on these
contracts so detection algorithms can be swapped without rewriting consumers.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from models.bar import Bar


class SwingType(Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingPoint:
    """A swing high or swing low candidate."""

    index: int
    price: float
    timestamp: datetime
    swing_type: SwingType


class SwingDetector(Protocol):
    """Detect swing highs/lows from completed bars."""

    def detect(self, bars: Sequence[Bar]) -> tuple[SwingPoint, ...]:
        """Return swing points in chronological order."""


class PlaceholderSwingDetector:
    """Reserved for Strategy V1 — does not detect swings yet."""

    def detect(self, bars: Sequence[Bar]) -> tuple[SwingPoint, ...]:
        _ = bars
        return ()
