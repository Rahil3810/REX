"""Catalog placeholders for planned strategy research experiments."""

from collections.abc import Sequence

from models.bar import Bar
from models.signal import Signal
from strategies.base_strategy import BaseStrategy


class _PlaceholderStrategy(BaseStrategy):
    """Non-trading placeholder: intentionally emits no signals."""

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        # TODO: Implement only after a documented hypothesis and test plan exist.
        return []


class S001_ZoneBreakout(_PlaceholderStrategy):
    # TODO(S001): Define and validate the ZoneBreakout hypothesis.
    strategy_id = "S001"
    strategy_name = "ZoneBreakout"
    description = "Placeholder for the zone-breakout research hypothesis."


class S003_MomentumPullback(_PlaceholderStrategy):
    # TODO(S003): Define and validate the MomentumPullback hypothesis.
    strategy_id = "S003"
    strategy_name = "MomentumPullback"
    description = "Placeholder for the momentum-pullback research hypothesis."


class S004_SessionBreakout(_PlaceholderStrategy):
    # TODO(S004): Define and validate the SessionBreakout hypothesis.
    strategy_id = "S004"
    strategy_name = "SessionBreakout"
    description = "Placeholder for the session-breakout research hypothesis."


class S005_TrendContinuation(_PlaceholderStrategy):
    # TODO(S005): Define and validate the TrendContinuation hypothesis.
    strategy_id = "S005"
    strategy_name = "TrendContinuation"
    description = "Placeholder for the trend-continuation research hypothesis."


class S006_RangeReversal(_PlaceholderStrategy):
    # TODO(S006): Define and validate the RangeReversal hypothesis.
    strategy_id = "S006"
    strategy_name = "RangeReversal"
    description = "Placeholder for the range-reversal research hypothesis."
