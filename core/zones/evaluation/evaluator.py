"""Zone Evaluation V1 — deterministic causal historical zone performance.

Separates zone *creation* from zone *evaluation*. Does not mutate zones or
``Zone.strength``. Methodology id: ``zone_eval_v1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from core.zones.auto.atr import causal_atr
from core.zones.auto.evidence import AutomaticZone
from core.zones.evaluation.config import ZoneEvaluationConfig
from core.zones.evaluation.models import (
    InteractionOutcome,
    ZoneEvaluation,
    ZoneInteractionEvaluation,
    aggregate_interactions,
)
from models.bar import Bar
from models.zone import Zone, ZoneKind


@dataclass(frozen=True)
class ZoneEvaluationSubject:
    """A zone plus the confirmation index when it became evaluable.

    Creation time is ``origin_confirmation_index`` (inclusive known-by bar).
    Evaluation only uses bars strictly after that index for interactions.
    """

    zone: Zone
    origin_confirmation_index: int
    symbol: str | None = None


class ZoneEvaluator:
    """Research evaluator for historical zone interaction behavior."""

    def __init__(self, config: ZoneEvaluationConfig | None = None) -> None:
        self.config = config or ZoneEvaluationConfig()

    def evaluate(
        self,
        zones: Sequence[Zone | AutomaticZone | ZoneEvaluationSubject],
        bars: Sequence[Bar],
        *,
        asof: datetime | None = None,
        asof_index: int | None = None,
        origins: Mapping[int, int] | None = None,
    ) -> tuple[ZoneEvaluation, ...]:
        """Evaluate one or more zones against ``bars``.

        Args:
            zones: ``Zone``, ``AutomaticZone``, or ``ZoneEvaluationSubject``.
            bars: Canonical OHLCV series.
            asof / asof_index: Evaluation cutoff (defaults to last bar).
            origins: Optional ``zone_id → origin_confirmation_index`` for bare Zones.

        Returns:
            One ``ZoneEvaluation`` per input zone (empty interactions if none).
        """
        if not bars:
            return ()

        end_index = self._resolve_asof_index(bars, asof=asof, asof_index=asof_index)
        if end_index is None:
            return ()

        results: list[ZoneEvaluation] = []
        for item in zones:
            subject = self._coerce_subject(item, origins=origins)
            results.append(
                self._evaluate_one(subject, bars, asof_index=end_index)
            )
        return tuple(results)

    def evaluate_one(
        self,
        zone: Zone | AutomaticZone | ZoneEvaluationSubject,
        bars: Sequence[Bar],
        *,
        asof: datetime | None = None,
        asof_index: int | None = None,
        origin_confirmation_index: int | None = None,
    ) -> ZoneEvaluation:
        origins = None
        if isinstance(zone, Zone) and origin_confirmation_index is not None:
            origins = {zone.id: origin_confirmation_index}
        result = self.evaluate(
            [zone],
            bars,
            asof=asof,
            asof_index=asof_index,
            origins=origins,
        )
        if not result:
            raise ValueError("Unable to evaluate zone: empty bars or invalid asof")
        return result[0]

    def _evaluate_one(
        self,
        subject: ZoneEvaluationSubject,
        bars: Sequence[Bar],
        *,
        asof_index: int,
    ) -> ZoneEvaluation:
        zone = subject.zone
        symbol = subject.symbol or (bars[0].symbol if bars else "")
        evaluated_at = bars[asof_index].timestamp
        start = subject.origin_confirmation_index + 1
        if start > asof_index:
            return aggregate_interactions(
                zone_id=zone.id,
                symbol=symbol,
                timeframe=zone.timeframe,
                zone_kind=zone.kind,
                evaluated_at=evaluated_at,
                config=self.config,
                interactions=(),
            )

        episodes = _detect_interaction_episodes(
            bars,
            zone=zone,
            start_index=start,
            asof_index=asof_index,
        )
        interactions: list[ZoneInteractionEvaluation] = []
        for interaction_index, (entry_index, exit_index) in enumerate(episodes):
            interactions.append(
                self._score_interaction(
                    bars=bars,
                    zone=zone,
                    interaction_index=interaction_index,
                    entry_index=entry_index,
                    exit_index=exit_index,
                    asof_index=asof_index,
                )
            )

        return aggregate_interactions(
            zone_id=zone.id,
            symbol=symbol,
            timeframe=zone.timeframe,
            zone_kind=zone.kind,
            evaluated_at=evaluated_at,
            config=self.config,
            interactions=interactions,
        )

    def _score_interaction(
        self,
        *,
        bars: Sequence[Bar],
        zone: Zone,
        interaction_index: int,
        entry_index: int,
        exit_index: int | None,
        asof_index: int,
    ) -> ZoneInteractionEvaluation:
        entry_bar = bars[entry_index]
        exit_time = None if exit_index is None else bars[exit_index].timestamp
        atr = causal_atr(
            bars,
            asof_index=entry_index,
            period=self.config.atr_period,
        )
        if atr is None or atr <= 0:
            return ZoneInteractionEvaluation(
                zone_id=zone.id,
                interaction_index=interaction_index,
                entry_index=entry_index,
                entry_time=entry_bar.timestamp,
                exit_index=exit_index,
                exit_time=exit_time,
                atr_at_interaction=None,
                mfe=None,
                mae=None,
                bars_to_target=None,
                bars_to_adverse=None,
                outcome=InteractionOutcome.UNAVAILABLE,
                break_detected=False,
                reason="ATR unavailable at interaction; no fabricated outcome.",
            )

        horizon_end = min(asof_index, entry_index + self.config.horizon_bars)
        if horizon_end <= entry_index:
            return ZoneInteractionEvaluation(
                zone_id=zone.id,
                interaction_index=interaction_index,
                entry_index=entry_index,
                entry_time=entry_bar.timestamp,
                exit_index=exit_index,
                exit_time=exit_time,
                atr_at_interaction=atr,
                mfe=None,
                mae=None,
                bars_to_target=None,
                bars_to_adverse=None,
                outcome=InteractionOutcome.UNAVAILABLE,
                break_detected=False,
                reason="Insufficient future horizon after interaction entry.",
            )

        kind = zone.kind
        if kind not in (ZoneKind.SUPPLY, ZoneKind.DEMAND):
            return ZoneInteractionEvaluation(
                zone_id=zone.id,
                interaction_index=interaction_index,
                entry_index=entry_index,
                entry_time=entry_bar.timestamp,
                exit_index=exit_index,
                exit_time=exit_time,
                atr_at_interaction=atr,
                mfe=None,
                mae=None,
                bars_to_target=None,
                bars_to_adverse=None,
                outcome=InteractionOutcome.UNAVAILABLE,
                break_detected=False,
                reason="Zone kind must be supply or demand for directional evaluation.",
            )

        entry_price = entry_bar.close
        target_distance = self.config.target_atr_multiple * atr
        stop_distance = self.config.invalidation_atr_multiple * atr

        mfe = 0.0
        mae = 0.0
        bars_to_target: int | None = None
        bars_to_adverse: int | None = None
        break_detected = False
        outcome: InteractionOutcome | None = None
        reason = ""

        for index in range(entry_index + 1, horizon_end + 1):
            bar = bars[index]
            offset = index - entry_index
            if kind is ZoneKind.SUPPLY:
                favorable = entry_price - bar.low
                adverse = bar.high - entry_price
                structurally_broken = bar.close > zone.high
            else:
                favorable = bar.high - entry_price
                adverse = entry_price - bar.low
                structurally_broken = bar.close < zone.low

            mfe = max(mfe, max(0.0, favorable))
            mae = max(mae, max(0.0, adverse))

            if structurally_broken and not break_detected:
                break_detected = True
                if outcome is None:
                    outcome = InteractionOutcome.BROKEN
                    reason = "Close invalidated the zone band (close-based break)."
                    bars_to_adverse = bars_to_adverse or offset

            if bars_to_target is None and favorable >= target_distance:
                bars_to_target = offset
                if outcome is None:
                    outcome = InteractionOutcome.SUCCESS
                    reason = (
                        f"Favorable excursion reached "
                        f"{self.config.target_atr_multiple}×ATR before invalidation."
                    )

            if bars_to_adverse is None and adverse >= stop_distance:
                bars_to_adverse = offset
                if outcome is None:
                    outcome = InteractionOutcome.FAILURE
                    reason = (
                        f"Adverse excursion reached "
                        f"{self.config.invalidation_atr_multiple}×ATR before target."
                    )

            if outcome is not None and outcome is not InteractionOutcome.UNAVAILABLE:
                # First decisive event wins; continue only to finalize MFE/MAE
                # through the event bar (already included).
                break

        if outcome is None:
            # Ran out of horizon without target or invalidation.
            outcome = InteractionOutcome.UNAVAILABLE
            reason = "Horizon ended before target or invalidation threshold."

        return ZoneInteractionEvaluation(
            zone_id=zone.id,
            interaction_index=interaction_index,
            entry_index=entry_index,
            entry_time=entry_bar.timestamp,
            exit_index=exit_index,
            exit_time=exit_time,
            atr_at_interaction=atr,
            mfe=mfe,
            mae=mae,
            bars_to_target=bars_to_target,
            bars_to_adverse=bars_to_adverse,
            outcome=outcome,
            break_detected=break_detected,
            reason=reason,
        )

    @staticmethod
    def _coerce_subject(
        item: Zone | AutomaticZone | ZoneEvaluationSubject,
        *,
        origins: Mapping[int, int] | None,
    ) -> ZoneEvaluationSubject:
        if isinstance(item, ZoneEvaluationSubject):
            return item
        if isinstance(item, AutomaticZone):
            return ZoneEvaluationSubject(
                zone=item.zone,
                origin_confirmation_index=item.evidence.origin_confirmation_index,
            )
        if isinstance(item, Zone):
            if origins is None or item.id not in origins:
                raise ValueError(
                    f"Bare Zone id={item.id} requires origins[zone_id] "
                    f"confirmation index (creation time)."
                )
            return ZoneEvaluationSubject(
                zone=item,
                origin_confirmation_index=int(origins[item.id]),
            )
        raise TypeError(f"Unsupported zone subject type: {type(item)!r}")

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


def _detect_interaction_episodes(
    bars: Sequence[Bar],
    *,
    zone: Zone,
    start_index: int,
    asof_index: int,
) -> list[tuple[int, int | None]]:
    """Detect independent touch episodes: enter → leave = one interaction.

    Overlap uses bar high/low (wick allowed for *touch*). Structural break for
    outcomes still uses close semantics in ``_score_interaction``.
    """
    episodes: list[tuple[int, int | None]] = []
    inside = False
    entry: int | None = None

    for index in range(start_index, asof_index + 1):
        bar = bars[index]
        overlaps = zone.overlaps_bar(bar.low, bar.high)
        if overlaps and not inside:
            entry = index
            inside = True
        elif not overlaps and inside:
            assert entry is not None
            episodes.append((entry, index - 1))
            entry = None
            inside = False

    if inside and entry is not None:
        episodes.append((entry, None))
    return episodes
