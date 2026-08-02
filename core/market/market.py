"""Market domain metadata (defaults shared by many instruments)."""

from dataclasses import dataclass
from enum import Enum

from core.market.capabilities import MarketCapabilities


class AssetClass(Enum):
    """High-level market domain."""

    FOREX = "forex"
    STOCKS = "stocks"
    CRYPTO = "crypto"
    FUTURES = "futures"


class VolumeSemantics(Enum):
    """Meaning of ``Bar.volume`` for instruments in this market."""

    NONE = "none"
    TICK = "tick"
    EXCHANGE = "exchange"


class SessionFamily(Enum):
    """
    Which calendar / session model applies by default.

    ``FOREX_MEGA`` corresponds to the existing Sydney/Tokyo/London/NY
    windows in ``SessionManager``. Exchange RTH calendars are not implemented.
    """

    FOREX_MEGA = "forex_mega"
    ALWAYS_OPEN = "always_open"
    EXCHANGE_RTH = "exchange_rth"


@dataclass(frozen=True)
class Market:
    """
    A market domain (forex, stocks, …) — not a single symbol.

    Engines should not branch on asset class; they read capabilities and
    volume/session metadata via the ``Instrument``.
    """

    id: str
    asset_class: AssetClass
    session_family: SessionFamily
    volume_semantics: VolumeSemantics
    capabilities: MarketCapabilities
    display_name: str = ""


# Built-in forex domain used by current research (EURUSD, GBPUSD, …).
FOREX = Market(
    id="forex",
    asset_class=AssetClass.FOREX,
    session_family=SessionFamily.FOREX_MEGA,
    volume_semantics=VolumeSemantics.TICK,
    capabilities=MarketCapabilities(
        supports_tick_volume=True,
        supports_exchange_volume=False,
        supports_open_interest=False,
        trades_24x7=False,
    ),
    display_name="Forex",
)
