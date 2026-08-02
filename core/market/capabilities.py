"""Market capability flags — prefer composition over asset-class subclasses."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketCapabilities:
    """What a market (or instrument override) can express."""

    supports_open_interest: bool = False
    supports_tick_volume: bool = False
    supports_exchange_volume: bool = False
    trades_24x7: bool = False
