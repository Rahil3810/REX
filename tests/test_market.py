"""Tests for the thin Market / Instrument metadata layer."""

import unittest
from datetime import datetime, timezone

from core.market import (
    FOREX,
    AlwaysOpenCalendar,
    AssetClass,
    Instrument,
    Market,
    MarketCapabilities,
    SessionFamily,
    VolumeSemantics,
    get_instrument,
    normalize_symbol,
    register_instrument,
    require_instrument,
    research_symbols,
)


class MarketModelTests(unittest.TestCase):
    def test_forex_market_defaults(self) -> None:
        self.assertEqual(FOREX.asset_class, AssetClass.FOREX)
        self.assertEqual(FOREX.session_family, SessionFamily.FOREX_MEGA)
        self.assertEqual(FOREX.volume_semantics, VolumeSemantics.TICK)
        self.assertTrue(FOREX.capabilities.supports_tick_volume)
        self.assertFalse(FOREX.capabilities.supports_open_interest)
        self.assertFalse(FOREX.capabilities.trades_24x7)

    def test_builtin_instruments_registered(self) -> None:
        eurusd = require_instrument("EURUSD")
        self.assertEqual(eurusd.market.id, "forex")
        self.assertEqual(eurusd.pip_size, 0.0001)
        self.assertEqual(eurusd.tick_size, 0.00001)
        self.assertEqual(eurusd.base_currency, "EUR")
        self.assertEqual(eurusd.quote_currency, "USD")

        usdjpy = require_instrument("USDJPY")
        self.assertEqual(usdjpy.effective_pip_size, 0.01)
        self.assertFalse(usdjpy.research_enabled)

        xau = require_instrument("XAUUSD")
        self.assertEqual(xau.effective_pip_size, 0.1)
        self.assertTrue(xau.research_enabled)

    def test_research_symbols_exclude_disabled(self) -> None:
        symbols = research_symbols()
        self.assertIn("EURUSD", symbols)
        self.assertIn("GBPUSD", symbols)
        self.assertIn("XAUUSD", symbols)
        self.assertNotIn("USDJPY", symbols)

    def test_capability_defaults_from_market(self) -> None:
        eurusd = require_instrument("EURUSD")
        self.assertTrue(eurusd.effective_capabilities.supports_tick_volume)
        self.assertFalse(eurusd.effective_capabilities.supports_exchange_volume)

    def test_instrument_capability_override(self) -> None:
        override = MarketCapabilities(
            supports_tick_volume=True,
            supports_exchange_volume=True,
            supports_open_interest=False,
            trades_24x7=True,
        )
        instrument = Instrument(
            symbol="TESTOVERRIDE",
            market=FOREX,
            tick_size=0.0001,
            pip_size=0.0001,
            capabilities=override,
            research_enabled=False,
        )
        self.assertTrue(instrument.effective_capabilities.trades_24x7)
        self.assertTrue(instrument.effective_capabilities.supports_exchange_volume)
        # Market defaults unchanged
        self.assertFalse(FOREX.capabilities.trades_24x7)

    def test_volume_semantics_override(self) -> None:
        instrument = Instrument(
            symbol="TESTVOL",
            market=FOREX,
            tick_size=0.01,
            volume_semantics=VolumeSemantics.NONE,
            research_enabled=False,
        )
        self.assertEqual(instrument.effective_volume_semantics, VolumeSemantics.NONE)
        self.assertEqual(FOREX.volume_semantics, VolumeSemantics.TICK)

    def test_distance_to_pips(self) -> None:
        eurusd = require_instrument("EURUSD")
        self.assertAlmostEqual(eurusd.distance_to_pips(0.0010), 10.0)

    def test_symbol_helpers_match_instrument(self) -> None:
        from core.market import distance_to_pips_for_symbol, pip_size_for_symbol

        self.assertEqual(pip_size_for_symbol("EURUSD"), 0.0001)
        self.assertEqual(pip_size_for_symbol("UNKNOWNPAIR"), 0.0001)
        self.assertAlmostEqual(distance_to_pips_for_symbol(0.0010, "EURUSD"), 10.0)

    def test_normalize_and_lookup(self) -> None:
        self.assertEqual(normalize_symbol("eur/usd"), "EURUSD")
        self.assertIsNotNone(get_instrument("eur/usd"))

    def test_register_custom_instrument(self) -> None:
        custom_market = Market(
            id="test_crypto",
            asset_class=AssetClass.CRYPTO,
            session_family=SessionFamily.ALWAYS_OPEN,
            volume_semantics=VolumeSemantics.EXCHANGE,
            capabilities=MarketCapabilities(
                supports_exchange_volume=True,
                trades_24x7=True,
            ),
            display_name="Test Crypto",
        )
        instrument = Instrument(
            symbol="BTCUSDT",
            market=custom_market,
            tick_size=0.01,
            research_enabled=False,
        )
        register_instrument(instrument)
        loaded = require_instrument("BTCUSDT")
        self.assertEqual(loaded.market.asset_class, AssetClass.CRYPTO)
        self.assertTrue(loaded.effective_capabilities.trades_24x7)
        self.assertEqual(loaded.effective_pip_size, 0.01)

    def test_invalid_tick_size_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Instrument(symbol="BAD", market=FOREX, tick_size=0.0)

    def test_always_open_calendar(self) -> None:
        calendar = AlwaysOpenCalendar()
        self.assertTrue(calendar.is_trading(datetime(2024, 1, 1, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
