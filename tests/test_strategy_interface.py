"""Tests for standardizing the strategy interface on Sequence[Bar]."""

import unittest
from datetime import datetime, timedelta
from collections.abc import Sequence

from models.bar import Bar
from models.signal import Signal, SignalType
from models.zone import Zone, ZoneBook
from strategies.base_strategy import BaseStrategy
from strategies.breakout import BreakoutStrategy
from backtests.backtest_runner import BacktestRunner
from core.signal_engine import SignalEngine
from core.data_feed import MockDataFeed


class MockCausalHistoryStrategy(BaseStrategy):
    strategy_id = "CAUSAL_TEST"
    strategy_name = "Causal History Test"
    description = "Test strategy to record the passed history sequence on each call."

    def __init__(self) -> None:
        self.calls: list[list[Bar]] = []

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        self.calls.append(list(candles))
        return []


def _make_bar(symbol: str, timestamp: datetime, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=close - 0.0010,
        high=close + 0.0020,
        low=close - 0.0020,
        close=close,
    )


class StrategyInterfaceTests(unittest.TestCase):
    def test_backtest_runner_causal_history(self) -> None:
        """Verify that BacktestRunner passes chronological, causal history only."""
        base_time = datetime(2026, 6, 20, 12, 0, 0)
        bars = [
            _make_bar("EURUSD", base_time, 1.1500),
            _make_bar("EURUSD", base_time + timedelta(minutes=15), 1.1510),
            _make_bar("EURUSD", base_time + timedelta(minutes=30), 1.1520),
        ]

        strategy = MockCausalHistoryStrategy()
        BacktestRunner().run(strategy, bars)

        # Strategy should have been called 3 times (once per candle)
        self.assertEqual(len(strategy.calls), 3)

        # Call 1: only the first candle
        self.assertEqual(len(strategy.calls[0]), 1)
        self.assertEqual(strategy.calls[0][0].timestamp, base_time)

        # Call 2: first and second candles, in chronological order
        self.assertEqual(len(strategy.calls[1]), 2)
        self.assertEqual(strategy.calls[1][0].timestamp, base_time)
        self.assertEqual(strategy.calls[1][1].timestamp, base_time + timedelta(minutes=15))

        # Call 3: all three candles, in chronological order, no future data
        self.assertEqual(len(strategy.calls[2]), 3)
        self.assertEqual(strategy.calls[2][0].timestamp, base_time)
        self.assertEqual(strategy.calls[2][1].timestamp, base_time + timedelta(minutes=15))
        self.assertEqual(strategy.calls[2][2].timestamp, base_time + timedelta(minutes=30))

    def test_signal_engine_isolation_and_reset(self) -> None:
        """Verify SignalEngine isolates history by symbol and clears on reset."""
        base_time = datetime(2026, 6, 20, 12, 0, 0)
        eurusd_bars = [
            _make_bar("EURUSD", base_time, 1.1500),
            _make_bar("EURUSD", base_time + timedelta(minutes=15), 1.1510),
        ]
        gbpusd_bars = [
            _make_bar("GBPUSD", base_time, 1.2500),
            _make_bar("GBPUSD", base_time + timedelta(minutes=15), 1.2510),
        ]

        zone_books = {
            "EURUSD": ZoneBook(symbol="EURUSD", zones=()),
            "GBPUSD": ZoneBook(symbol="GBPUSD", zones=()),
        }

        # Setup mock data feed that streams per-symbol
        demo_bars = {
            "EURUSD": eurusd_bars,
            "GBPUSD": gbpusd_bars,
        }
        data_feed = MockDataFeed(bars=demo_bars)
        engine = SignalEngine(data_feed=data_feed, zone_books=zone_books)

        # Inject our mock history recording strategies
        eurusd_strategy = MockCausalHistoryStrategy()
        gbpusd_strategy = MockCausalHistoryStrategy()
        engine._strategies["EURUSD"] = eurusd_strategy
        engine._strategies["GBPUSD"] = gbpusd_strategy

        # Run the engine for both symbols
        engine.run(["EURUSD", "GBPUSD"])

        # EURUSD strategy should only receive EURUSD candles
        self.assertEqual(len(eurusd_strategy.calls), 2)
        for call in eurusd_strategy.calls:
            for bar in call:
                self.assertEqual(bar.symbol, "EURUSD")

        # GBPUSD strategy should only receive GBPUSD candles
        self.assertEqual(len(gbpusd_strategy.calls), 2)
        for call in gbpusd_strategy.calls:
            for bar in call:
                self.assertEqual(bar.symbol, "GBPUSD")

        # Check that the internal history dictionary is populated
        self.assertEqual(len(engine._history["EURUSD"]), 2)
        self.assertEqual(len(engine._history["GBPUSD"]), 2)

        # Reset the engine and verify cleanup to prevent leaks between runs
        engine.reset()
        self.assertEqual(len(engine._history["EURUSD"]), 0)
        self.assertEqual(len(engine._history["GBPUSD"]), 0)
        self.assertEqual(len(engine.get_signals()), 0)

    def test_breakout_strategy_unchanged_behavior(self) -> None:
        """Verify BreakoutStrategy generates unchanged signals via BacktestRunner."""
        zone_book = ZoneBook(
            symbol="EURUSD",
            zones=(
                Zone(
                    id=1,
                    name="weekly_support",
                    low=1.1500,
                    high=1.1520,
                    timeframe="weekly",
                    strength=9,
                ),
            ),
        )
        base_time = datetime(2026, 6, 20, 12, 0, 0)
        bars = [
            # 1. Close below zone
            Bar("EURUSD", base_time, 1.1490, 1.1495, 1.1485, 1.1490),
            # 2. Touch and close inside zone (Enter zone)
            Bar("EURUSD", base_time + timedelta(minutes=15), 1.1510, 1.1515, 1.1505, 1.1510),
            # 3. Break above zone
            Bar("EURUSD", base_time + timedelta(minutes=30), 1.1530, 1.1535, 1.1515, 1.1530),
        ]

        # Scenario A: Running BreakoutStrategy using BacktestRunner
        strategy = BreakoutStrategy(zone_book=zone_book)
        runner_result = BacktestRunner().run(strategy, bars)

        # Check signal outcomes
        runner_signals = runner_result.signal_outcomes
        self.assertEqual(len(runner_signals), 4)

        # 1. Close outside
        self.assertEqual(runner_signals[0].signal_type, SignalType.CLOSE_OUTSIDE)
        # 2. Enter zone
        self.assertEqual(runner_signals[1].signal_type, SignalType.ENTER_ZONE)
        # 3. Break above (and close outside)
        self.assertEqual(runner_signals[2].signal_type, SignalType.BREAK_ABOVE)
        self.assertEqual(runner_signals[3].signal_type, SignalType.CLOSE_OUTSIDE)

    def test_backtest_runner_isolation(self) -> None:
        """Verify that BacktestRunner isolates history by symbol in multi-symbol datasets."""
        base_time = datetime(2026, 6, 20, 12, 0, 0)
        # Interleaved timestamps of EURUSD and GBPUSD bars
        bars = [
            _make_bar("EURUSD", base_time, 1.1500),
            _make_bar("GBPUSD", base_time, 1.2500),
            _make_bar("EURUSD", base_time + timedelta(minutes=15), 1.1510),
            _make_bar("GBPUSD", base_time + timedelta(minutes=15), 1.2510),
        ]

        strategy = MockCausalHistoryStrategy()
        BacktestRunner().run(strategy, bars)

        # Strategy should have been called 4 times (2 for EURUSD, 2 for GBPUSD)
        self.assertEqual(len(strategy.calls), 4)

        # Traces of calls:
        # Call 0 (EURUSD, index 0): history has [EURUSD 12:00]
        self.assertEqual(len(strategy.calls[0]), 1)
        self.assertEqual(strategy.calls[0][0].symbol, "EURUSD")

        # Call 1 (GBPUSD, index 1): history has [GBPUSD 12:00]
        self.assertEqual(len(strategy.calls[1]), 1)
        self.assertEqual(strategy.calls[1][0].symbol, "GBPUSD")

        # Call 2 (EURUSD, index 2): history has [EURUSD 12:00, EURUSD 12:15]
        self.assertEqual(len(strategy.calls[2]), 2)
        self.assertEqual(strategy.calls[2][0].symbol, "EURUSD")
        self.assertEqual(strategy.calls[2][1].symbol, "EURUSD")

        # Call 3 (GBPUSD, index 3): history has [GBPUSD 12:00, GBPUSD 12:15]
        self.assertEqual(len(strategy.calls[3]), 2)
        self.assertEqual(strategy.calls[3][0].symbol, "GBPUSD")
        self.assertEqual(strategy.calls[3][1].symbol, "GBPUSD")


if __name__ == "__main__":
    unittest.main()
