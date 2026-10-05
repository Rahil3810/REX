"""Immutable research feature snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from core.features.packs.base import FeaturePack
from core.features.types import PackId
from core.market import Instrument
from models.bar import Bar


@dataclass(frozen=True)
class FeatureContext:
    """
    Point-in-time immutable snapshot of selected feature packs.

    Strategies (Phase 2+) consume this object; they must not recompute features.
    There is no confidence integer on this type.
    """

    instrument: Instrument
    asof: datetime
    entry_timeframe: str
    bars_by_timeframe: Mapping[str, tuple[Bar, ...]]
    packs: Mapping[PackId, FeaturePack]
    schema_hash: str
    multi_timeframe_mapping: Mapping[str, tuple[str, ...]]

    def pack(self, pack_id: PackId) -> FeaturePack:
        try:
            return self.packs[pack_id]
        except KeyError as exc:
            raise KeyError(f"Feature pack not materialized: {pack_id}") from exc

    def require_pack(self, pack_id: PackId, expected_type: type) -> object:
        payload = self.pack(pack_id)
        if not isinstance(payload, expected_type):
            raise TypeError(
                f"Pack {pack_id!r} expected {expected_type.__name__}, "
                f"got {type(payload).__name__}"
            )
        return payload


def freeze_bars(
    bars_by_timeframe: Mapping[str, tuple[Bar, ...]],
) -> Mapping[str, tuple[Bar, ...]]:
    return MappingProxyType(dict(bars_by_timeframe))


def freeze_packs(
    packs: Mapping[PackId, FeaturePack],
) -> Mapping[PackId, FeaturePack]:
    return MappingProxyType(dict(packs))
