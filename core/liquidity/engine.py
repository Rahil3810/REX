"""Liquidity engine package — Strategy V1 placeholder (no trading logic)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from core.market import Instrument
from models.bar import Bar


@dataclass(frozen=True)
class LiquiditySnapshot:
    """Reserved liquidity context for a symbol/price."""

    symbol: str
    notes: str = "Liquidity analysis is not implemented yet."


class LiquidityEngine(Protocol):
    """Future liquidity queries (pools, sweeps, resting liquidity)."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
    ) -> LiquiditySnapshot:
        """Return a liquidity snapshot (when implemented)."""


class PlaceholderLiquidityEngine:
    """Reserved for Strategy V1 — no liquidity logic yet."""

    def analyze(
        self,
        bars: Sequence[Bar],
        instrument: Instrument,
    ) -> LiquiditySnapshot:
        _ = bars
        return LiquiditySnapshot(symbol=instrument.symbol)
