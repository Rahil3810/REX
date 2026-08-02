"""Change of Character (CHoCH) detection contracts — Strategy V1 placeholders."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.market_structure.bos import StructureBreakDirection
from core.market_structure.swing import SwingPoint
from models.bar import Bar


@dataclass(frozen=True)
class ChangeOfCharacterEvent:
    """A detected change of character (when implemented)."""

    index: int
    timestamp: datetime
    direction: StructureBreakDirection
    broken_level: float
    confirming_price: float


class CHoCHDetector(Protocol):
    """Detect Change of Character events from bars and/or swings."""

    def detect(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingPoint] = (),
    ) -> tuple[ChangeOfCharacterEvent, ...]:
        """Return CHoCH events in chronological order."""


class PlaceholderCHoCHDetector:
    """Reserved for Strategy V1 — CHoCH logic is not implemented."""

    def detect(
        self,
        bars: Sequence[Bar],
        swings: Sequence[SwingPoint] = (),
    ) -> tuple[ChangeOfCharacterEvent, ...]:
        _ = bars, swings
        return ()

