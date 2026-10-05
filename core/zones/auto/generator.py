"""Automatic zone generation entrypoint (research primitive)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from core.features.config import SwingDetectionConfig, default_feature_config
from core.features.generators.swings import SwingEvent, SwingGenerator
from core.market import Instrument, require_instrument
from core.zones.auto.candidates import (
    SwingClusterZoneGeneratorV1,
    ZoneCandidateGenerator,
)
from core.zones.auto.config import SwingClusterZoneConfig
from core.zones.auto.evidence import AutomaticZone
from models.bar import Bar


class AutomaticZoneGenerator:
    """Generate automatic zones from OHLCV + confirmed SwingEvents.

    Default candidate generator is ``SwingClusterZoneGeneratorV1``.
    Alternative generators (e.g. future KDE) can be injected via
    ``candidate_generator`` without changing the canonical Zone model.
    """

    def __init__(
        self,
        *,
        swing_config: SwingDetectionConfig | None = None,
        cluster_config: SwingClusterZoneConfig | None = None,
        candidate_generator: ZoneCandidateGenerator | None = None,
    ) -> None:
        self.swing_config = swing_config or default_feature_config().swing_detection
        self.cluster_config = cluster_config or SwingClusterZoneConfig()
        self.candidate_generator: ZoneCandidateGenerator = (
            candidate_generator
            if candidate_generator is not None
            else SwingClusterZoneGeneratorV1(self.cluster_config)
        )
        self._swing_generator = SwingGenerator(self.swing_config)

    def generate(
        self,
        bars: Sequence[Bar],
        *,
        timeframe: str,
        asof: datetime | None = None,
        asof_index: int | None = None,
        instrument: Instrument | str | None = None,
        swings: Sequence[SwingEvent] | None = None,
    ) -> tuple[AutomaticZone, ...]:
        """Generate automatic zones causally as of ``asof`` / ``asof_index``.

        Args:
            bars: Canonical OHLCV bars for one timeframe.
            timeframe: Timeframe label stored on zones/swings.
            asof: Optional evaluation timestamp. Defaults to last bar time.
            asof_index: Optional bar index. Defaults to last index / resolved from asof.
            instrument: Optional instrument (defaults to first bar symbol).
            swings: Optional precomputed SwingEvents (must already be causal).
                When omitted, swings are generated with confirmation_time <= asof.

        Returns:
            Deterministic tuple of AutomaticZone (canonical Zone + evidence).
            Empty when data/swings are insufficient — never fabricates zones.
        """
        if not bars:
            return ()

        resolved_index = self._resolve_asof_index(bars, asof=asof, asof_index=asof_index)
        if resolved_index is None:
            return ()
        asof_time = bars[resolved_index].timestamp
        prefix = bars[: resolved_index + 1]

        if swings is None:
            symbol = (
                instrument.symbol
                if isinstance(instrument, Instrument)
                else (instrument or bars[0].symbol)
            )
            inst = (
                instrument
                if isinstance(instrument, Instrument)
                else require_instrument(str(symbol))
            )
            features = self._swing_generator.generate(
                {timeframe: prefix},
                inst,
                entry_timeframe=timeframe,
                asof=asof_time,
            )
            swing_events = features.by_timeframe[timeframe].swings
        else:
            swing_events = tuple(
                swing
                for swing in swings
                if swing.confirmation_index <= resolved_index
                and swing.confirmation_time <= asof_time
            )

        return self.candidate_generator.generate_candidates(
            prefix,
            swing_events,
            timeframe=timeframe,
            asof_index=resolved_index,
            asof_time=asof_time,
        )

    @staticmethod
    def _resolve_asof_index(
        bars: Sequence[Bar],
        *,
        asof: datetime | None,
        asof_index: int | None,
    ) -> int | None:
        if asof_index is not None:
            if asof_index < 0 or asof_index >= len(bars):
                return None
            return asof_index
        if asof is None:
            return len(bars) - 1
        chosen: int | None = None
        for index, bar in enumerate(bars):
            if bar.timestamp <= asof:
                chosen = index
            else:
                break
        return chosen
