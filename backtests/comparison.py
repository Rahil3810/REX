"""Run and rank multiple strategies against one historical dataset."""

from collections.abc import Iterable

from backtests.backtest_runner import BacktestRunner, OutcomeProvider
from backtests.results import BacktestResult
from models.bar import Bar
from strategies.registry import StrategyRegistry


class StrategyComparison:
    """Comparison service with deterministic performance ranking."""

    def __init__(
        self,
        registry: StrategyRegistry,
        runner: BacktestRunner | None = None,
    ) -> None:
        self.registry = registry
        self.runner = runner or BacktestRunner()

    def run_strategy(
        self,
        strategy_id: str,
        bars: Iterable[Bar],
        *,
        strategy_kwargs: dict[str, object] | None = None,
        outcome_provider: OutcomeProvider | None = None,
    ) -> BacktestResult:
        strategy = self.registry.create(strategy_id, **(strategy_kwargs or {}))
        return self.runner.run(strategy, bars, outcome_provider)

    def run_strategies(
        self,
        strategy_ids: Iterable[str],
        bars: Iterable[Bar],
        *,
        outcome_provider: OutcomeProvider | None = None,
    ) -> list[BacktestResult]:
        dataset = tuple(bars)
        results = [
            self.run_strategy(
                strategy_id,
                dataset,
                outcome_provider=outcome_provider,
            )
            for strategy_id in strategy_ids
        ]
        return self.rank(results)

    @staticmethod
    def rank(results: Iterable[BacktestResult]) -> list[BacktestResult]:
        """Rank by profit factor, then expectancy, then win rate."""
        def key(result: BacktestResult) -> tuple[float, float, float]:
            profit_factor = (
                result.profit_factor
                if result.profit_factor is not None
                else float("-inf")
            )
            return (profit_factor, result.expectancy, result.win_rate)

        return sorted(results, key=key, reverse=True)

