"""PositionSizer: risk amount and position size from account context."""

from dataclasses import dataclass
from typing import Protocol

from models.account_context import AccountContext
from models.trade_setup import TradeSetup


@dataclass(frozen=True)
class SizeResult:
    """Sizing outcome for a planned trade."""

    position_size: float
    risk_amount: float


class PositionSizer(Protocol):
    """Compute position size and risk amount from entry, stop, and account."""

    def size(
        self,
        setup: TradeSetup,
        entry: float,
        stop: float,
        account: AccountContext,
    ) -> SizeResult | None:
        """Return size parameters, or None when sizing is impossible."""
        ...


class FixedRiskSizer:
    """Size so that stop distance risks a fixed fraction of account equity."""

    def size(
        self,
        setup: TradeSetup,
        entry: float,
        stop: float,
        account: AccountContext,
    ) -> SizeResult | None:
        stop_distance = abs(entry - stop)
        if stop_distance <= 1e-12:
            return None
        if account.equity <= 0 or account.risk_fraction <= 0:
            return None

        risk_amount = account.equity * account.risk_fraction
        position_size = risk_amount / stop_distance
        return SizeResult(position_size=position_size, risk_amount=risk_amount)
