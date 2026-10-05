"""Protocols for primitive and derived feature generators."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from core.market import Instrument
from models.bar import Bar


class PrimitiveGenerator(Protocol):
    """Computes features from bars + instrument without other detectors."""

    feature_id: str

    def generate(
        self,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        instrument: Instrument,
        *,
        entry_timeframe: str,
    ) -> object:
        """Return a pack-local payload (typically a frozen dataclass)."""


class DerivedGenerator(Protocol):
    """Computes features that declare dependence on prior pack payloads."""

    feature_id: str
    requires: tuple[str, ...]

    def generate(
        self,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        instrument: Instrument,
        *,
        entry_timeframe: str,
        prior: Mapping[str, object],
    ) -> object:
        """Return a pack-local payload using ``prior`` pack results."""
