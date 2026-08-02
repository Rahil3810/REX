"""Sequential strategy backtesting and comparison tools."""

from backtests.backtest_runner import BacktestRunner
from backtests.results import BacktestResult, SignalOutcome

__all__ = ["BacktestResult", "BacktestRunner", "SignalOutcome"]

