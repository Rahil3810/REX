"""Structural Break of Structure (BOS) — swing-referenced, method swing_bos_v1.

Bullish BOS: closed candle closes strictly above the most recent confirmed
SwingEvent(kind=HIGH) with confirmation_index < break_index.

Bearish BOS: closed candle closes strictly below the most recent confirmed
SwingEvent(kind=LOW) with confirmation_index < break_index.

A swing that has already produced a BOS is consumed and will not emit again.
Detection is a pure function of the candle prefix + swing events (deterministic).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core.features.generators.swings import SwingEvent, SwingKind
from core.features.types import METHOD_STRUCTURE_SWING_BOS_V1, MethodId
from models.bar import Bar


class BOSDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True)
class StructuralBOSEvent:
    """One structural BOS occurrence referencing an exact SwingEvent."""

    method_id: str
    direction: BOSDirection
    broken_swing: SwingEvent
    break_index: int
    break_time: datetime
    break_close: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "method_id": self.method_id,
            "direction": self.direction.value,
            "broken_swing": self.broken_swing.to_dict(),
            "break_index": self.break_index,
            "break_time": self.break_time.isoformat(),
            "break_close": self.break_close,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StructuralBOSResult:
    """Result of evaluating BOS on the latest candle of a causal prefix."""

    method_id: str
    detected: bool
    event: StructuralBOSEvent | None
    reason: str
    series: tuple[StructuralBOSEvent, ...] = ()

    @property
    def bullish(self) -> bool:
        return bool(
            self.detected
            and self.event is not None
            and self.event.direction == BOSDirection.BULLISH
        )

    @property
    def bearish(self) -> bool:
        return bool(
            self.detected
            and self.event is not None
            and self.event.direction == BOSDirection.BEARISH
        )


def detect_swing_bos_series(
    bars: Sequence[Bar],
    swings: Sequence[SwingEvent],
    *,
    method_id: MethodId | str = METHOD_STRUCTURE_SWING_BOS_V1,
) -> tuple[StructuralBOSEvent, ...]:
    """
    Scan ``bars`` chronologically and emit structural BOS events.

    Only swings with ``confirmation_index < j`` are eligible at candle ``j``.
    Each swing id is consumed after it produces one BOS.
    """
    method = str(method_id)
    consumed: set[str] = set()
    events: list[StructuralBOSEvent] = []

    for break_index, bar in enumerate(bars):
        # Bullish: most recent eligible HIGH
        high = _most_recent_eligible(
            swings, kind=SwingKind.HIGH, break_index=break_index, consumed=consumed
        )
        if high is not None and bar.close > high.price:
            events.append(
                StructuralBOSEvent(
                    method_id=method,
                    direction=BOSDirection.BULLISH,
                    broken_swing=high,
                    break_index=break_index,
                    break_time=bar.timestamp,
                    break_close=bar.close,
                    reason=(
                        f"Bullish BOS: close {bar.close} broke confirmed swing high "
                        f"{high.id} @ {high.price}."
                    ),
                )
            )
            consumed.add(high.id)

        # Bearish: most recent eligible LOW
        low = _most_recent_eligible(
            swings, kind=SwingKind.LOW, break_index=break_index, consumed=consumed
        )
        if low is not None and bar.close < low.price:
            events.append(
                StructuralBOSEvent(
                    method_id=method,
                    direction=BOSDirection.BEARISH,
                    broken_swing=low,
                    break_index=break_index,
                    break_time=bar.timestamp,
                    break_close=bar.close,
                    reason=(
                        f"Bearish BOS: close {bar.close} broke confirmed swing low "
                        f"{low.id} @ {low.price}."
                    ),
                )
            )
            consumed.add(low.id)

    return tuple(events)


def detect_swing_bos(
    bars: Sequence[Bar],
    swings: Sequence[SwingEvent],
    *,
    method_id: MethodId | str = METHOD_STRUCTURE_SWING_BOS_V1,
) -> StructuralBOSResult:
    """
    Evaluate whether the **last** candle of ``bars`` is a structural BOS bar.

    Series history is still scanned so swing consumption is causal/deterministic.
    """
    method = str(method_id)
    if not bars:
        return StructuralBOSResult(
            method_id=method,
            detected=False,
            event=None,
            reason="No candles supplied.",
            series=(),
        )

    series = detect_swing_bos_series(bars, swings, method_id=method)
    last_index = len(bars) - 1
    on_last = tuple(event for event in series if event.break_index == last_index)
    if not on_last:
        return StructuralBOSResult(
            method_id=method,
            detected=False,
            event=None,
            reason="No structural BOS on the latest candle.",
            series=series,
        )
    # Prefer the first event on that candle (bullish checked before bearish).
    event = on_last[0]
    return StructuralBOSResult(
        method_id=method,
        detected=True,
        event=event,
        reason=event.reason,
        series=series,
    )


def _most_recent_eligible(
    swings: Sequence[SwingEvent],
    *,
    kind: SwingKind,
    break_index: int,
    consumed: set[str],
) -> SwingEvent | None:
    eligible = [
        swing
        for swing in swings
        if swing.kind == kind
        and swing.confirmation_index < break_index
        and swing.id not in consumed
    ]
    if not eligible:
        return None
    # Most recent structural swing by source index (then confirmation).
    return max(eligible, key=lambda swing: (swing.index, swing.confirmation_index))
