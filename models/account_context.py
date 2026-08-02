"""Account context for position sizing (research defaults; not a broker account)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountContext:
    """
    Explicit capital assumptions for sizing. Not live brokerage state.

    Kept intentionally small (equity + risk fraction only). A future Portfolio
    model can *compose* this context (or a richer account snapshot) alongside
    open positions and cash — without requiring margin/leverage fields here
    and without breaking existing constructors that rely on these defaults.
    """

    equity: float = 10_000.0
    risk_fraction: float = 0.01
