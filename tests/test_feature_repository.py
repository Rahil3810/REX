"""Tests for FeatureRepository materialization."""

import unittest
from datetime import datetime, timedelta

from core.features import (
    FeatureRepository,
    PACK_PRICE,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
)
from core.features.packs.base import PricePack, StructurePack, VolatilityPack
from core.market import require_instrument
from models.bar import Bar


def _bars(symbol: str, count: int = 40) -> list[Bar]:
    bars: list[Bar] = []
    timestamp = datetime(2026, 6, 20, 0, 0, 0)
    for index in range(count):
        close = 1.1000 + 0.0005 * index
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp + timedelta(minutes=15 * index),
                open=close - 0.0003,
                high=close + 0.0006,
                low=close - 0.0006,
                close=close,
            )
        )
    return bars


class FeatureRepositoryTests(unittest.TestCase):
    def test_materialize_selected_packs(self) -> None:
        repo = FeatureRepository()
        context = repo.materialize(
            require_instrument("EURUSD"),
            {"M15": _bars("EURUSD")},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE, PACK_STRUCTURE, PACK_VOLATILITY),
        )

        self.assertIn(PACK_PRICE, context.packs)
        self.assertIn(PACK_STRUCTURE, context.packs)
        self.assertIn(PACK_VOLATILITY, context.packs)
        self.assertIsInstance(context.require_pack(PACK_PRICE, PricePack), PricePack)
        self.assertIsInstance(
            context.require_pack(PACK_STRUCTURE, StructurePack), StructurePack
        )
        self.assertIsInstance(
            context.require_pack(PACK_VOLATILITY, VolatilityPack), VolatilityPack
        )
        self.assertTrue(context.schema_hash)

    def test_context_is_immutable_mapping(self) -> None:
        repo = FeatureRepository()
        context = repo.materialize(
            "EURUSD",
            {"M15": _bars("EURUSD")},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE,),
        )
        with self.assertRaises(TypeError):
            context.packs[PACK_PRICE] = context.packs[PACK_PRICE]  # type: ignore[index]

    def test_unknown_pack_raises(self) -> None:
        from core.features.types import PackId

        repo = FeatureRepository()
        with self.assertRaises(KeyError):
            repo.materialize(
                "EURUSD",
                {"M15": _bars("EURUSD")},
                entry_timeframe="M15",
                pack_ids=(PackId("does_not_exist"),),
            )


if __name__ == "__main__":
    unittest.main()
