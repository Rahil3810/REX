"""Unit and integration tests for LiquiditySweepStrategy."""

import unittest
from datetime import datetime, timedelta
from collections.abc import Sequence

from models.bar import Bar
from models.signal import Signal, SignalType
from strategies.base_strategy import BaseStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy
from strategies.registry import build_default_registry


def _make_bar(
    symbol: str,
    timestamp: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


class LiquiditySweepStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.strategy = LiquiditySweepStrategy(
            lookback=5,
            min_wick_ratio=0.50,
            tolerance=0.0,
            require_close_inside=True,
        )
        self.base_time = datetime(2026, 6, 20, 12, 0, 0)

    def test_bullish_sweep_signal_generation(self) -> None:
        """Verify a bullish sweep triggers the BULLISH_SWEEP signal type."""
        # Swing Low at index 2 (1.1400)
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1510, 1.1400, 1.1500),  # swing low
            _make_bar("EURUSD", self.base_time + timedelta(minutes=45), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=60), 1.1500, 1.1510, 1.1490, 1.1500),
            # Current candle (index 5) breaks 1.1400 but closes above it (1.1450) with large wick
            # low = 1.1380, close = 1.1450, open = 1.1500 -> body = 0.0050, lower wick = 0.0070 -> ratio = 0.58 >= 0.50
            _make_bar("EURUSD", self.base_time + timedelta(minutes=75), 1.1500, 1.1510, 1.1380, 1.1450),
        ]

        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, SignalType.BULLISH_SWEEP)
        self.assertEqual(signals[0].price, 1.1450)
        self.assertEqual(signals[0].zone_id, 0)
        self.assertIn("Bullish", signals[0].reason)

    def test_bearish_sweep_signal_generation(self) -> None:
        """Verify a bearish sweep triggers the BEARISH_SWEEP signal type."""
        # Swing High at index 2 (1.1600)
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1600, 1.1490, 1.1500),  # swing high
            _make_bar("EURUSD", self.base_time + timedelta(minutes=45), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=60), 1.1500, 1.1510, 1.1490, 1.1500),
            # Current candle (index 5) breaks 1.1600 but closes below it (1.1550) with large upper wick
            # high = 1.1620, close = 1.1550, open = 1.1500 -> body = 0.0050, upper wick = 0.0070 -> ratio = 0.58 >= 0.50
            _make_bar("EURUSD", self.base_time + timedelta(minutes=75), 1.1500, 1.1620, 1.1490, 1.1550),
        ]

        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, SignalType.BEARISH_SWEEP)
        self.assertEqual(signals[0].price, 1.1550)
        self.assertEqual(signals[0].zone_id, 0)
        self.assertIn("Bearish", signals[0].reason)

    def test_no_signal_when_sweep_conditions_not_met(self) -> None:
        """Verify no signal is emitted if rules do not detect a sweep."""
        # Simple flat bars
        bars = [
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15 * i), 1.1500, 1.1510, 1.1490, 1.1500)
            for i in range(6)
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 0)

    def test_insufficient_history(self) -> None:
        """Verify no signals are generated if candles length is less than lookback + 1."""
        bars = [
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15 * i), 1.1500, 1.1510, 1.1490, 1.1500)
            for i in range(4)  # lookback is 5, so we need at least 6 bars
        ]
        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 0)

    def test_chronological_repeated_evaluation_without_duplicate_signals(self) -> None:
        """Verify repeated calls on the same timestamp emit no duplicate signals."""
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1510, 1.1400, 1.1500),  # swing low
            _make_bar("EURUSD", self.base_time + timedelta(minutes=45), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=60), 1.1500, 1.1510, 1.1490, 1.1500),
            _make_bar("EURUSD", self.base_time + timedelta(minutes=75), 1.1500, 1.1510, 1.1380, 1.1450),  # sweep
        ]

        # First evaluation: triggers a signal
        signals_1 = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals_1), 1)

        # Second evaluation (same bars/same timestamp): should return no signals
        signals_2 = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals_2), 0)

        # Append a new candle (with a later timestamp) that also triggers a sweep
        bars.append(
            _make_bar("EURUSD", self.base_time + timedelta(minutes=90), 1.1500, 1.1510, 1.1350, 1.1450)
        )

        # Evaluation on new candle should emit a signal
        signals_3 = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals_3), 1)

    def test_registry_integration(self) -> None:
        """Verify the registry discovers and is able to instantiate S008."""
        registry = build_default_registry()
        self.assertIn("S008", registry.ids())
        
        strategy_class = registry.get("S008")
        self.assertEqual(strategy_class.strategy_name, "Liquidity Sweep V1")
        
        # Instantiate through registry
        inst = registry.create("S008", lookback=12, min_wick_ratio=0.7)
        self.assertTrue(isinstance(inst, LiquiditySweepStrategy))
        self.assertEqual(inst.lookback, 12)
        self.assertEqual(inst.min_wick_ratio, 0.7)

    def test_older_candles_outside_lookback_do_not_affect_result(self) -> None:
        """Verify that candles older than lookback + 1 do not affect sweep detection."""
        # Swing Low is at index 5 (1.1400), lookback is 5, total bars is 9 (index 0 to 8).
        # Sweep happens at index 8 (current, low=1.1380).
        # We place a very low low at index 0 (low=1.1200). Since lookback is 5, 
        # index 0 is outside the lookback window.
        # If the window is bounded, the swing low is correctly detected as 1.1400 (at index 5), 
        # and index 8 sweeps it. If index 0 is incorrectly included, the swing low would be 1.1200, 
        # and index 8 would NOT sweep it.
        bars = [
            _make_bar("EURUSD", self.base_time, 1.1500, 1.1510, 1.1200, 1.1500),  # index 0: extreme low outside window
            _make_bar("EURUSD", self.base_time + timedelta(minutes=15), 1.1500, 1.1510, 1.1490, 1.1500), # index 1
            _make_bar("EURUSD", self.base_time + timedelta(minutes=30), 1.1500, 1.1510, 1.1490, 1.1500), # index 2
            _make_bar("EURUSD", self.base_time + timedelta(minutes=45), 1.1500, 1.1510, 1.1490, 1.1500), # index 3
            _make_bar("EURUSD", self.base_time + timedelta(minutes=60), 1.1500, 1.1510, 1.1490, 1.1500), # index 4
            _make_bar("EURUSD", self.base_time + timedelta(minutes=75), 1.1500, 1.1510, 1.1400, 1.1500), # index 5: actual swing low
            _make_bar("EURUSD", self.base_time + timedelta(minutes=90), 1.1500, 1.1510, 1.1490, 1.1500), # index 6
            _make_bar("EURUSD", self.base_time + timedelta(minutes=105), 1.1500, 1.1510, 1.1490, 1.1500), # index 7
            _make_bar("EURUSD", self.base_time + timedelta(minutes=120), 1.1500, 1.1510, 1.1380, 1.1450), # index 8: current/sweep
        ]

        signals = self.strategy.generate_signals(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal, SignalType.BULLISH_SWEEP)


if __name__ == "__main__":
    unittest.main()
