"""ExecutionPolicy: opportunity pricing without position sizing.

Current design keeps construction decisions in one ExecutionPolicy.

Future evolution (documentation only — not implemented): independent
policies may split concerns without changing TradePlanner's orchestration role:

- EntryPolicy — when/how entry is intended
- StopPolicy — stop placement
- TargetPolicy — take-profit / R-multiple targets
- ExpiryPolicy — opportunity or plan timeout

Until those exist, FixedRiskRewardPolicy owns entry model, stop, target, and
timeout together. Do not split the protocol until a second concrete need appears.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from models.bar import Bar
from models.entry_model import EntryModel
from models.trade_direction import TradeDirection
from models.trade_setup import TradeSetup


@dataclass(frozen=True)
class PolicyResult:
    """Resolved construction parameters owned by an ExecutionPolicy."""

    entry_model: EntryModel
    entry_price: float
    sl_price: float
    tp_price: float
    r_multiple: float
    timeout_candles: int


class ExecutionPolicy(Protocol):
    """Determine entry, stop, take-profit, and expiry from a TradeSetup."""

    def build(
        self,
        setup: TradeSetup,
        candles: Sequence[Bar],
    ) -> PolicyResult | None:
        """Return construction parameters, or None if the setup cannot be priced."""
        ...


class FixedRiskRewardPolicy:
    """
    Default policy: structural stop from setup hints, fixed R-multiple target.

    Uses stop_hint and entry hints from TradeSetup. Does not size positions.
    """

    def __init__(self, r_multiple: float = 2.0, timeout_candles: int = 5) -> None:
        if r_multiple <= 0:
            raise ValueError("r_multiple must be positive")
        if timeout_candles < 1:
            raise ValueError("timeout_candles must be >= 1")
        self.r_multiple = r_multiple
        self.timeout_candles = timeout_candles

    def build(
        self,
        setup: TradeSetup,
        candles: Sequence[Bar],
    ) -> PolicyResult | None:
        if setup.stop_hint is None:
            return None
        if not candles:
            return None

        entry_model = setup.entry_model_hint or EntryModel.NEXT_CANDLE_OPEN
        # Planned entry estimate: explicit hint, else last close (fill may differ).
        entry_price = (
            setup.entry_hint if setup.entry_hint is not None else candles[-1].close
        )
        sl_price = setup.stop_hint

        risk_distance = abs(entry_price - sl_price)
        if risk_distance <= 1e-12:
            return None

        if setup.direction == TradeDirection.LONG:
            if sl_price >= entry_price:
                return None
            if setup.target_hint is not None:
                tp_price = setup.target_hint
            else:
                tp_price = entry_price + risk_distance * self.r_multiple
        else:
            if sl_price <= entry_price:
                return None
            if setup.target_hint is not None:
                tp_price = setup.target_hint
            else:
                tp_price = entry_price - risk_distance * self.r_multiple

        timeout = (
            setup.timeout_candles
            if setup.timeout_candles is not None
            else self.timeout_candles
        )
        return PolicyResult(
            entry_model=entry_model,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            r_multiple=self.r_multiple,
            timeout_candles=timeout,
        )
