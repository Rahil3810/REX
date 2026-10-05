"""In-memory FeatureRepository — materializes FeatureContext snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from core.features.config import (
    DEFAULT_FEATURE_CONFIG_PATH,
    FeatureConfig,
    default_feature_config,
    load_feature_config,
)
from core.features.context import FeatureContext, freeze_bars, freeze_packs
from core.features.packs.base import FeaturePack
from core.features.registry import (
    FeaturePackRegistry,
    build_default_registry,
    resolve_pack_ids,
)
from core.features.timeframes import (
    ensure_utc,
    normalize_bar_timestamp,
    prepare_causal_bars,
)
from core.features.types import PackId
from core.market import Instrument, require_instrument
from models.bar import Bar

if TYPE_CHECKING:
    from core.indicators.indicator_engine import IndicatorEngine
    from core.zones.engine import ZoneEngine


def _load_default_config() -> FeatureConfig:
    if DEFAULT_FEATURE_CONFIG_PATH.is_file():
        return load_feature_config(DEFAULT_FEATURE_CONFIG_PATH)
    return default_feature_config()


@dataclass(frozen=True)
class MaterializeArgs:
    """Internal builder arguments passed to pack factories."""

    instrument: Instrument
    bars_by_timeframe: Mapping[str, tuple[Bar, ...]]
    entry_timeframe: str
    asof: datetime
    config: FeatureConfig
    zone_engine: ZoneEngine | None
    indicator_engine: IndicatorEngine | None


class FeatureRepository:
    """
    In-memory materializer for research feature packs.

    Not a persistent feature store. Deterministic for fixed inputs + config.

    Causal contract: ``materialize(..., asof=T)`` builds packs only from bars
    available at ``T``. Configured higher timeframes are constructed from the
    finest aggregatable lower timeframe when possible, and only **completed**
    HTF bars (``completion_time <= T``) are admitted before feature calculation.
    """

    def __init__(
        self,
        config: FeatureConfig | None = None,
        registry: FeaturePackRegistry | None = None,
        *,
        zone_engine: ZoneEngine | None = None,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        self._config = config or _load_default_config()
        self._registry = registry or build_default_registry()
        self._zone_engine = zone_engine
        self._indicator_engine = indicator_engine

    @property
    def config(self) -> FeatureConfig:
        return self._config

    def materialize(
        self,
        instrument: Instrument | str,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        *,
        entry_timeframe: str,
        asof: datetime | None = None,
        pack_ids: Sequence[PackId] | None = None,
    ) -> FeatureContext:
        resolved_instrument = (
            instrument
            if isinstance(instrument, Instrument)
            else require_instrument(instrument)
        )
        normalized = self._normalize_bars(resolved_instrument.symbol, bars_by_timeframe)

        resolved_asof = self._resolve_asof(
            asof=asof,
            entry_timeframe=entry_timeframe,
            bars_by_timeframe=normalized,
        )

        higher = self._config.multi_timeframe_mapping.get(entry_timeframe, ())
        causal = prepare_causal_bars(
            normalized,
            entry_timeframe=entry_timeframe,
            asof=resolved_asof,
            higher_timeframes=higher,
            symbol=resolved_instrument.symbol,
        )

        if entry_timeframe not in causal or not causal[entry_timeframe]:
            raise ValueError(f"Missing entry timeframe candles: {entry_timeframe}")

        selected = resolve_pack_ids(pack_ids)
        args = MaterializeArgs(
            instrument=resolved_instrument,
            bars_by_timeframe=causal,
            entry_timeframe=entry_timeframe,
            asof=resolved_asof,
            config=self._config,
            zone_engine=self._zone_engine,
            indicator_engine=self._indicator_engine,
        )
        packs: dict[PackId, FeaturePack] = {}
        for pack_id in selected:
            builder = self._registry.get(pack_id)
            packs[pack_id] = builder(args)  # type: ignore[assignment]

        schema_hash = _schema_hash(selected)
        return FeatureContext(
            instrument=resolved_instrument,
            asof=resolved_asof,
            entry_timeframe=entry_timeframe,
            bars_by_timeframe=freeze_bars(causal),
            packs=freeze_packs(packs),
            schema_hash=schema_hash,
            multi_timeframe_mapping=dict(self._config.multi_timeframe_mapping),
        )

    @staticmethod
    def _resolve_asof(
        *,
        asof: datetime | None,
        entry_timeframe: str,
        bars_by_timeframe: Mapping[str, tuple[Bar, ...]],
    ) -> datetime:
        if asof is not None:
            return ensure_utc(asof)
        entry_bars = bars_by_timeframe.get(entry_timeframe, ())
        if entry_bars:
            return ensure_utc(entry_bars[-1].timestamp)
        # Allow constructing entry from LTF when asof is provided by caller only.
        # Without asof and without entry bars we cannot establish T.
        raise ValueError(
            f"Missing entry timeframe candles: {entry_timeframe} "
            "(provide entry bars or an explicit asof with aggregatable LTF source)"
        )

    @staticmethod
    def _normalize_bars(
        symbol: str,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
    ) -> dict[str, tuple[Bar, ...]]:
        normalized: dict[str, tuple[Bar, ...]] = {}
        for timeframe, bars in bars_by_timeframe.items():
            if not timeframe:
                raise ValueError("Timeframe cannot be empty")
            symbol_bars = [
                normalize_bar_timestamp(bar) for bar in bars if bar.symbol == symbol
            ]
            if len(symbol_bars) != len(bars):
                raise ValueError(f"All bars for {timeframe} must match {symbol}")
            normalized[timeframe] = tuple(
                sorted(symbol_bars, key=lambda bar: bar.timestamp)
            )
        return normalized


def _schema_hash(pack_ids: Sequence[PackId]) -> str:
    payload = ",".join(sorted(pack_ids))
    return sha256(payload.encode("utf-8")).hexdigest()[:16]
