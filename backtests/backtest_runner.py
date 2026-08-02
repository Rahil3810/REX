"""Chronological, candle-by-candle strategy replay."""

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime

from backtests.fill_models import FillModel
from backtests.metrics import calculate_metrics, calculate_trade_metrics
from backtests.results import BacktestResult, SignalOutcome
from backtests.trade_simulator import TradeSimulator
from execution.factories import SweepTradeSetupFactory, TradeSetupFactory
from execution.planner import TradePlanner
from execution.policies import FixedRiskRewardPolicy
from execution.sizers import FixedRiskSizer
from execution.validators import TradeSetupValidationError, TradeSetupValidator
from core.market import research_symbols
from models.account_context import AccountContext
from models.bar import Bar
from models.signal import Signal

OutcomeProvider = Callable[[Signal, Sequence[Bar]], float | None]


class BacktestDataError(ValueError):
    """Raised when historical candles are unsuitable for a backtest."""


class BacktestRunner:
    """
    Replay completed candles without exposing future candles to the strategy.

    Trade simulation path:
        Signal → TradeSetupFactory → TradeSetupValidator → TradePlanner → TradePlan
        → TradeSimulator (backtest executor).
    """

    def run(
        self,
        strategy: object,
        bars: Iterable[Bar],
        outcome_provider: OutcomeProvider | None = None,
        simulate_trades: bool = False,
        fill_model: FillModel | None = None,
        trade_planner: TradePlanner | None = None,
        setup_factory: TradeSetupFactory | None = None,
        setup_validator: TradeSetupValidator | None = None,
        account: AccountContext | None = None,
        *,
        risk_policy: object | None = None,
    ) -> BacktestResult:
        if risk_policy is not None:
            raise TypeError(
                "risk_policy is removed. Pass trade_planner=TradePlanner(...) "
                "with FixedRiskRewardPolicy / FixedRiskSizer instead."
            )

        ordered_bars = self._prepare_bars(bars)
        records: list[SignalOutcome] = []
        histories: dict[str, list[Bar]] = {}

        if hasattr(strategy, "reset") and callable(strategy.reset):
            strategy.reset()

        simulator = None
        planner = None
        factory = None
        validator = None
        strategy_id = getattr(strategy, "strategy_id", strategy.__class__.__name__)
        strategy_name = getattr(strategy, "strategy_name", strategy.__class__.__name__)

        if simulate_trades:
            max_hold = getattr(strategy, "max_hold_candles", 60)
            simulator = TradeSimulator(max_hold_candles=max_hold, fill_model=fill_model)
            r_mult = getattr(strategy, "r_multiple", 2.0)
            planner = trade_planner or TradePlanner(
                policy=FixedRiskRewardPolicy(r_multiple=r_mult),
                sizer=FixedRiskSizer(),
                account=account,
            )
            factory = setup_factory or SweepTradeSetupFactory()
            validator = setup_validator or TradeSetupValidator()

        ignored_active_lifecycle_count = 0
        rejected_policy_boundary_count = 0
        accepted_setups_count = 0
        currently_active_count = 0

        for bar in ordered_bars:
            if bar.symbol not in histories:
                histories[bar.symbol] = []
            symbol_history = histories[bar.symbol]
            symbol_history.append(bar)

            if simulator is not None:
                simulator.update(bar)

            signals = self._generate_signals(strategy, bar, symbol_history)

            if simulator is not None:
                assert planner is not None and factory is not None and validator is not None
                for signal in signals:
                    if simulator.has_active_lifecycle(strategy_id, bar.symbol):
                        ignored_active_lifecycle_count += 1
                        continue

                    setup = factory.create(signal, symbol_history, strategy_id)
                    if setup is None:
                        rejected_policy_boundary_count += 1
                        continue

                    try:
                        setup = validator.validate(setup)
                    except TradeSetupValidationError:
                        rejected_policy_boundary_count += 1
                        continue

                    plan = planner.plan(setup, symbol_history)
                    if plan is None:
                        rejected_policy_boundary_count += 1
                        continue

                    simulator.add_plan(plan)
                    accepted_setups_count += 1

            for signal in signals:
                outcome = (
                    outcome_provider(signal, symbol_history)
                    if outcome_provider is not None
                    else None
                )
                records.append(
                    SignalOutcome(
                        symbol=signal.symbol,
                        timestamp=signal.timestamp,
                        signal_type=signal.signal.value,
                        zone_id=signal.zone_id,
                        price=signal.price,
                        outcome=outcome,
                    )
                )

        if simulator is not None:
            final_bars = {}
            for bar in ordered_bars:
                final_bars[bar.symbol] = bar
            symbols_list = tuple(sorted(histories.keys()))
            simulator.finalize_backtest(symbols_list, final_bars)

            closed_trades = simulator.get_all_closed_trades()
            terminated_setups = tuple(simulator.terminated_setups)
            metrics = calculate_trade_metrics(len(records), closed_trades)
            closed_trades_tuple = tuple(closed_trades)
            currently_active_count = simulator.get_currently_active_count()
        else:
            realized = [record.outcome for record in records if record.outcome is not None]
            metrics = calculate_metrics(len(records), realized)
            closed_trades_tuple = ()
            terminated_setups = ()

        symbols = tuple(sorted(histories.keys()))
        return BacktestResult.from_metrics(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            symbols=symbols,
            started_at=ordered_bars[0].timestamp if ordered_bars else None,
            ended_at=ordered_bars[-1].timestamp if ordered_bars else None,
            metrics=metrics,
            signal_outcomes=tuple(records),
            closed_trades=closed_trades_tuple,
            terminated_setups=terminated_setups,
            ignored_active_lifecycle_count=ignored_active_lifecycle_count,
            rejected_policy_boundary_count=rejected_policy_boundary_count,
            accepted_setups_count=accepted_setups_count,
            currently_active_count=currently_active_count,
        )

    def _prepare_bars(self, bars: Iterable[Bar]) -> list[Bar]:
        prepared = list(bars)
        for bar in prepared:
            supported = research_symbols()
            if bar.symbol not in supported:
                raise BacktestDataError(
                    f"Unsupported backtest symbol '{bar.symbol}'. "
                    f"Supported: {sorted(supported)}"
                )
            self._validate_bar(bar)

        ordered = sorted(prepared, key=lambda bar: (bar.timestamp, bar.symbol))
        seen: set[tuple[str, datetime]] = set()
        for bar in ordered:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                raise BacktestDataError(
                    f"Duplicate candle for {bar.symbol} at {bar.timestamp.isoformat()}"
                )
            seen.add(key)
        return ordered

    def _validate_bar(self, bar: Bar) -> None:
        if bar.high < bar.low:
            raise BacktestDataError(
                f"Invalid candle at {bar.timestamp.isoformat()}: high is below low"
            )
        if not bar.low <= bar.open <= bar.high:
            raise BacktestDataError(
                f"Invalid candle at {bar.timestamp.isoformat()}: open outside range"
            )
        if not bar.low <= bar.close <= bar.high:
            raise BacktestDataError(
                f"Invalid candle at {bar.timestamp.isoformat()}: close outside range"
            )

    def _generate_signals(
        self, strategy: object, bar: Bar, history: Sequence[Bar]
    ) -> list[Signal]:
        generator = getattr(strategy, "generate_signals", None)
        if callable(generator):
            return generator(history)
        legacy_evaluate = getattr(strategy, "evaluate", None)
        if callable(legacy_evaluate):
            return legacy_evaluate(bar)
        raise TypeError(
            f"{strategy.__class__.__name__} must implement generate_signals(candles)"
        )
