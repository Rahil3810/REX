"""Simple return series primitive."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log

from core.market import Instrument
from models.bar import Bar


@dataclass(frozen=True)
class TimeframeReturns:
    timeframe: str
    simple_returns: tuple[float, ...]
    log_returns: tuple[float, ...]


@dataclass(frozen=True)
class ReturnFeatures:
    by_timeframe: Mapping[str, TimeframeReturns]


class ReturnsGenerator:
    """Close-to-close simple and log returns per timeframe."""

    feature_id = "returns"

    def generate(
        self,
        bars_by_timeframe: Mapping[str, Sequence[Bar]],
        instrument: Instrument,
        *,
        entry_timeframe: str,
    ) -> ReturnFeatures:
        _ = instrument, entry_timeframe
        by_timeframe: dict[str, TimeframeReturns] = {}
        for timeframe, bars in bars_by_timeframe.items():
            ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
            simple: list[float] = []
            logs: list[float] = []
            for index in range(1, len(ordered)):
                previous = ordered[index - 1].close
                current = ordered[index].close
                if previous == 0:
                    simple.append(0.0)
                    logs.append(0.0)
                    continue
                simple.append((current - previous) / previous)
                if previous > 0 and current > 0:
                    logs.append(log(current / previous))
                else:
                    logs.append(0.0)
            by_timeframe[timeframe] = TimeframeReturns(
                timeframe=timeframe,
                simple_returns=tuple(simple),
                log_returns=tuple(logs),
            )
        return ReturnFeatures(by_timeframe=by_timeframe)
