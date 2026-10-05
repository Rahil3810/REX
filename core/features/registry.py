"""In-memory feature pack registration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from core.features.types import (
    DEFAULT_PACK_IDS,
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
    PACK_ZONES,
    PackId,
)

if TYPE_CHECKING:
    from core.features.repository import MaterializeArgs

PackBuilder = Callable[["MaterializeArgs"], object]


class FeaturePackRegistry:
    """Maps pack ids to builder callables. Extensible without editing callers."""

    def __init__(self) -> None:
        self._builders: dict[PackId, PackBuilder] = {}

    def register(self, pack_id: PackId, builder: PackBuilder) -> None:
        self._builders[pack_id] = builder

    def get(self, pack_id: PackId) -> PackBuilder:
        try:
            return self._builders[pack_id]
        except KeyError as exc:
            raise KeyError(f"Unknown feature pack: {pack_id}") from exc

    def known_pack_ids(self) -> tuple[PackId, ...]:
        return tuple(self._builders.keys())


def build_default_registry() -> FeaturePackRegistry:
    """Register core Phase-1 packs. SMC dialect packs are not registered here."""
    from core.features import packs as pack_builders

    registry = FeaturePackRegistry()

    def price(args: MaterializeArgs) -> object:
        return pack_builders.build_price_pack(
            args.bars_by_timeframe,
            args.instrument,
            entry_timeframe=args.entry_timeframe,
        )

    def structure(args: MaterializeArgs) -> object:
        return pack_builders.build_structure_pack(
            args.bars_by_timeframe,
            args.instrument,
            entry_timeframe=args.entry_timeframe,
            config=args.config,
            asof=args.asof,
        )

    def volatility(args: MaterializeArgs) -> object:
        return pack_builders.build_volatility_pack(
            args.bars_by_timeframe,
            args.instrument,
            entry_timeframe=args.entry_timeframe,
            config=args.config,
            indicator_engine=args.indicator_engine,
        )

    def indicators(args: MaterializeArgs) -> object:
        return pack_builders.build_indicator_pack(
            args.bars_by_timeframe,
            entry_timeframe=args.entry_timeframe,
            config=args.config,
            indicator_engine=args.indicator_engine,
        )

    def zones(args: MaterializeArgs) -> object:
        price = None
        entry_bars = args.bars_by_timeframe.get(args.entry_timeframe, ())
        if entry_bars:
            price = entry_bars[-1].close
        return pack_builders.build_zone_pack(
            args.instrument,
            price=price,
            zone_engine=args.zone_engine,
        )

    def session(args: MaterializeArgs) -> object:
        return pack_builders.build_session_pack(asof=args.asof)

    registry.register(PACK_PRICE, price)
    registry.register(PACK_STRUCTURE, structure)
    registry.register(PACK_VOLATILITY, volatility)
    registry.register(PACK_INDICATORS, indicators)
    registry.register(PACK_ZONES, zones)
    registry.register(PACK_SESSION, session)
    return registry


def resolve_pack_ids(pack_ids: Sequence[PackId] | None) -> tuple[PackId, ...]:
    if pack_ids is None:
        return DEFAULT_PACK_IDS
    return tuple(pack_ids)
