"""Tests for chronological replay, metrics, exports, and comparison."""

from collections.abc import Sequence
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from backtests.backtest_runner import BacktestDataError, BacktestRunner
from backtests.comparison import StrategyComparison
from backtests.results import BacktestResult
from models.bar import Bar
from models.signal import Signal, SignalType
from strategies.base_strategy import BaseStrategy


class SignalEveryBarStrategy(BaseStrategy):
    strategy_id = "TEST"
    strategy_name = "Test Strategy"
    description = "Test-only deterministic signal generator."

    def __init__(self) -> None:
        self.seen: list[datetime] = []

    def generate_signals(self, candles: Sequence[Bar]) -> list[Signal]:
        bar = candles[-1]
        self.seen.append(bar.timestamp)
        return [
            Signal(
                symbol=bar.symbol,
                signal=SignalType.ENTER_ZONE,
                zone_id=1,
                price=bar.close,
                timestamp=bar.timestamp,
                reason="test",
            )
        ]


def make_bar(minutes: int, symbol: str = "EURUSD") -> Bar:
    close = 1.10 + minutes / 10000
    return Bar(
        symbol=symbol,
        timestamp=datetime(2026, 6, 20, 12) + timedelta(minutes=minutes),
        open=close,
        high=close + 0.01,
        low=close - 0.01,
        close=close,
    )


class BacktestingTests(unittest.TestCase):
    def test_replays_chronologically_and_exposes_only_history(self) -> None:
        strategy = SignalEveryBarStrategy()
        history_lengths: list[int] = []
        outcomes = {0: 2.0, 15: -1.0, 30: 0.0}

        def outcome_provider(signal: Signal, history: tuple[Bar, ...]) -> float:
            history_lengths.append(len(history))
            minute = signal.timestamp.minute
            self.assertEqual(history[-1].timestamp, signal.timestamp)
            return outcomes[minute]

        result = BacktestRunner().run(
            strategy,
            [make_bar(30), make_bar(0), make_bar(15)],
            outcome_provider,
        )

        self.assertEqual(strategy.seen, sorted(strategy.seen))
        self.assertEqual(history_lengths, [1, 2, 3])
        self.assertEqual(result.total_signals, 3)
        self.assertEqual(result.wins, 1)
        self.assertEqual(result.losses, 1)
        self.assertEqual(result.win_rate, 50.0)
        self.assertEqual(result.profit_factor, 2.0)
        self.assertAlmostEqual(result.expectancy, 1 / 3)
        self.assertEqual(result.max_drawdown, 1.0)
        self.assertEqual(result.largest_win, 2.0)
        self.assertEqual(result.largest_loss, -1.0)

    def test_rejects_bad_candles_and_duplicate_timestamps(self) -> None:
        runner = BacktestRunner()
        duplicate = make_bar(0)
        with self.assertRaises(BacktestDataError):
            runner.run(SignalEveryBarStrategy(), [duplicate, duplicate])

        bad = replace(make_bar(15), high=1.0, low=1.2)
        with self.assertRaises(BacktestDataError):
            runner.run(SignalEveryBarStrategy(), [bad])

    def test_exports_json_csv_and_excel(self) -> None:
        result = BacktestRunner().run(SignalEveryBarStrategy(), [make_bar(0)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = result.export_json(root / "result.json")
            csv_path = result.export_csv(root / "result.csv")
            self.assertEqual(json.loads(json_path.read_text())["total_signals"], 1)
            self.assertIn("total_signals", csv_path.read_text())

            try:
                import openpyxl  # noqa: F401
            except ImportError:
                return
            excel_path = result.export_excel(root / "result.xlsx")
            self.assertTrue(excel_path.exists())

    def test_comparison_ranking_order(self) -> None:
        base = BacktestResult(
            strategy_id="A",
            strategy_name="A",
            symbols=("EURUSD",),
            started_at=None,
            ended_at=None,
            total_signals=1,
            wins=1,
            losses=0,
            win_rate=100,
            profit_factor=1.0,
            average_win=1,
            average_loss=0,
            expectancy=1,
            max_drawdown=0,
            largest_win=1,
            largest_loss=0,
        )
        results = [
            replace(base, strategy_id="A", profit_factor=1.0, expectancy=2),
            replace(base, strategy_id="B", profit_factor=2.0, expectancy=0),
            replace(base, strategy_id="C", profit_factor=1.0, expectancy=3),
        ]
        ranked = StrategyComparison.rank(results)
        self.assertEqual([result.strategy_id for result in ranked], ["B", "C", "A"])


if __name__ == "__main__":
    unittest.main()

