"""Break of Structure (BOS) detection contracts — Strategy V1 placeholders."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from core.market_structure.swing import SwingPoint
from models.bar import Bar


class StructureBreakDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True)
class StructureBreakEvent:
    """A detected break of structure (when implemented)."""

    index: int
    timestamp: datetime
    direction: StructureBreakDirection
    broken_level: float
    confirming_price: float


class BOSDetector(Protocol):
    """Detect Break of Structure events from bars and/or swings."""

    def detect(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingPoint] = (),
    ) -> tuple[StructureBreakEvent, ...]:
        """Return BOS events in chronological order."""


class PlaceholderBOSDetector:
    """Reserved for Strategy V1 — BOS logic is not implemented."""

    def detect(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingPoint] = (),
    ) -> tuple[StructureBreakEvent, ...]:
        _ = bars, swings
        return ()
