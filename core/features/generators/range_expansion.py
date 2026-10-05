"""Range-expansion primitive — renamed from legacy body-size MomentumAnalyzer."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.features.config import RangeExpansionConfig
from core.market import Instrument
from models.bar import Bar
from models.market_structure import RangeExpansionState


@dataclass(frozen=True)
class RangeExpansionFeatures:
    """Recent vs historical candle-body size classification."""

    state: RangeExpansionState
    reason: str
    ratio: float | None


class RangeExpansionGenerator:
    """Compare recent average body size to historical average body size."""

    feature_id = "range_expansion"

    def __init__(self, config: RangeExpansionConfig) -> None:
        self._config = config

    def generate(
        self,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        instrument: Instrument,
        *,
        entry_timeframe: str,
    ) -> RangeExpansionFeatures:
        _ = instrument
        bars = tuple(bars_by_timeframe.get(entry_timeframe, ()))
        if len(bars) < self._config.historical_window:
            return RangeExpansionFeatures(
                state=RangeExpansionState.UNAVAILABLE,
                reason=(
                    "Not enough completed candles for configured range-expansion "
                    "window; range expansion unavailable."
                ),
                ratio=None,
            )

        historical_bars = bars[-self._config.historical_window :]
        recent_bars = bars[-self._config.recent_window :]
        historical_average = _average_body_size(historical_bars)
        recent_average = _average_body_size(recent_bars)
        if historical_average == 0:
            return RangeExpansionFeatures(
                state=RangeExpansionState.UNAVAILABLE,
                reason=(
                    "Historical candle body average is zero; ratio undefined; "
                    "range expansion unavailable."
                ),
                ratio=None,
            )

        ratio = recent_average / historical_average
        if ratio < self._config.low_ratio:
            state = RangeExpansionState.LOW
        elif ratio > self._config.high_ratio:
            state = RangeExpansionState.HIGH
        else:
            state = RangeExpansionState.NORMAL
        return RangeExpansionFeatures(
            state=state,
            reason=(
                f"Recent average candle body {recent_average:.5f} versus "
                f"historical average {historical_average:.5f}; ratio {ratio:.2f}."
            ),
            ratio=ratio,
        )


def _average_body_size(bars: Sequence[Bar]) -> float:
    return sum(abs(bar.close - bar.open) for bar in bars) / len(bars)
