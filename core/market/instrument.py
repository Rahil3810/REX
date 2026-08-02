"""Instrument metadata — one tradeable symbol bound to a Market."""

from __future__ import annotations

from dataclasses import dataclass

from core.market.capabilities import MarketCapabilities
from core.market.market import FOREX, Market, VolumeSemantics


def normalize_symbol(symbol: str) -> str:
    """Canonical symbol key (uppercase, no separators)."""
    return symbol.upper().replace("/", "").replace("-", "").replace("_", "")


@dataclass(frozen=True)
class Instrument:
    """
    A concrete tradeable (e.g. EURUSD).

    Engines consume this instead of symbol-specific hardcoding.
    """

    symbol: str
    market: Market
    tick_size: float
    pip_size: float | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    volume_semantics: VolumeSemantics | None = None
    capabilities: MarketCapabilities | None = None
    research_enabled: bool = True

    def __post_init__(self) -> None:
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be > 0, got {self.tick_size}")
        if self.pip_size is not None and self.pip_size <= 0:
            raise ValueError(f"pip_size must be > 0 when set, got {self.pip_size}")

    @property
    def effective_pip_size(self) -> float:
        """Pip size for research distances; falls back to tick size."""
        return self.pip_size if self.pip_size is not None else self.tick_size

    @property
    def effective_volume_semantics(self) -> VolumeSemantics:
        if self.volume_semantics is not None:
            return self.volume_semantics
        return self.market.volume_semantics

    @property
    def effective_capabilities(self) -> MarketCapabilities:
        if self.capabilities is not None:
            return self.capabilities
        return self.market.capabilities

    def distance_to_pips(self, distance: float) -> float:
        """Convert a raw price distance into pips using this instrument."""
        return distance / self.effective_pip_size


_REGISTRY: dict[str, Instrument] = {}


def register_instrument(instrument: Instrument) -> None:
    """Register or replace an instrument in the process-local catalog."""
    _REGISTRY[normalize_symbol(instrument.symbol)] = instrument


def get_instrument(symbol: str) -> Instrument | None:
    """Return a registered instrument, or None if unknown."""
    return _REGISTRY.get(normalize_symbol(symbol))


def require_instrument(symbol: str) -> Instrument:
    """Return a registered instrument or raise ``KeyError``."""
    instrument = get_instrument(symbol)
    if instrument is None:
        raise KeyError(f"No Instrument registered for symbol {symbol!r}")
    return instrument


def registered_instruments() -> tuple[Instrument, ...]:
    """All registered instruments (stable order by symbol)."""
    return tuple(sorted(_REGISTRY.values(), key=lambda item: item.symbol))


def research_symbols() -> frozenset[str]:
    """Symbols marked ``research_enabled`` (backtest allowlist source)."""
    return frozenset(
        instrument.symbol
        for instrument in _REGISTRY.values()
        if instrument.research_enabled
    )


def pip_size_for_symbol(symbol: str) -> float:
    """
    Resolve pip size from the instrument catalog.

    Unregistered symbols keep the legacy generic FX fallback (0.0001)
    so existing call sites do not change behaviour.
    """
    instrument = get_instrument(symbol)
    if instrument is not None:
        return instrument.effective_pip_size
    return 0.0001


def distance_to_pips_for_symbol(distance: float, symbol: str) -> float:
    """Convert a price distance to pips via ``Instrument`` metadata when registered."""
    instrument = get_instrument(symbol)
    if instrument is not None:
        return instrument.distance_to_pips(distance)
    return distance / pip_size_for_symbol(symbol)


def _register_default_forex_instruments() -> None:
    """Seed catalog that replaces former hardcoded pip / symbol maps."""
    defaults = (
        Instrument(
            symbol="EURUSD",
            market=FOREX,
            tick_size=0.00001,
            pip_size=0.0001,
            base_currency="EUR",
            quote_currency="USD",
            research_enabled=True,
        ),
        Instrument(
            symbol="GBPUSD",
            market=FOREX,
            tick_size=0.00001,
            pip_size=0.0001,
            base_currency="GBP",
            quote_currency="USD",
            research_enabled=True,
        ),
        Instrument(
            symbol="USDJPY",
            market=FOREX,
            tick_size=0.001,
            pip_size=0.01,
            base_currency="USD",
            quote_currency="JPY",
            research_enabled=False,
        ),
        Instrument(
            symbol="XAUUSD",
            market=FOREX,
            tick_size=0.01,
            pip_size=0.1,
            base_currency="XAU",
            quote_currency="USD",
            research_enabled=True,
        ),
    )
    for instrument in defaults:
        register_instrument(instrument)


_register_default_forex_instruments()
