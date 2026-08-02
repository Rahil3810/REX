# REX

REX is a quantitative trading **research** platform. It helps you form hypotheses, replay historical data causally, and measure results under explicit assumptions.

It does **not** place live broker orders, manage portfolios, or connect to exchanges today.

For why REX exists, engineering rules, current architecture, and roadmap, use the documentation system below—not this README.

---

## Documentation

| Document | Responsibility |
|----------|----------------|
| [VISION.md](VISION.md) | Why REX exists |
| [PRINCIPLES.md](PRINCIPLES.md) | Engineering constitution |
| [ROADMAP.md](ROADMAP.md) | Phases, focus, deferred work |
| [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) | Current architecture and capabilities |
| [research/README.md](research/README.md) | Research process howto |

---

## Quick overview

- **Strategies** implement `generate_signals(candles)` and are discovered by the registry (detection only).
- **Execution layer** (`execution/`): `Signal` → `TradeSetup` → `TradePlan` via factory, validator, policy, and sizer.
- Directions use `TradeDirection` (`LONG` / `SHORT`). Plans carry `planned_at` (when produced).
- Pending-plan `timeout_candles` is enforced (`EXPIRED` after that many unfilled wait bars).
- **BacktestRunner** replays bars causally; trade mode feeds `TradePlan` into `TradeSimulator`.
- **Historical data** comes from Dukascopy via `historical/` (M1).
- **Two research modes:** signal studies, or trade simulation (`simulate_trades=True`).
- **Current strategies:** zone breakout (`CORE_ZONE_BREAKOUT`), liquidity sweep (`S008`). See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## Installation

```bash
python -m pip install -r requirements.txt
```

---

## Historical data setup

Configure `config/historical_data.json`, then download:

```bash
python -m historical.downloader
```

Data is stored under `data/historical/{SYMBOL}/M1/{YEAR}.csv`.

Load bars in research code:

```python
from datetime import date
from historical import HistoricalDataProvider

bars = HistoricalDataProvider().get_bars(
    "EURUSD",
    "M1",
    date(2024, 1, 1),
    date(2024, 12, 31),
)
```

---

## Running a backtest

Signal study (counts signals; outcomes only if you supply an outcome provider):

```python
from backtests.backtest_runner import BacktestRunner
from strategies.liquidity_sweep import LiquiditySweepStrategy

strategy = LiquiditySweepStrategy(lookback=10)
result = BacktestRunner().run(strategy, bars)
result.export_json(output_path)
```

Trade simulation (factory → validator → planner → simulator):

```python
from execution import FixedRiskRewardPolicy, FixedRiskSizer, TradePlanner

planner = TradePlanner(
    policy=FixedRiskRewardPolicy(r_multiple=2.0),
    sizer=FixedRiskSizer(),
)
result = BacktestRunner().run(
    strategy,
    bars,
    simulate_trades=True,
    trade_planner=planner,  # optional; defaults are created if omitted
)
```

**Note:** The default `SweepTradeSetupFactory` handles liquidity-sweep signals only. Other signal types are rejected at the opportunity boundary. Pipeline details: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

Registry usage:

```python
from strategies.registry import build_default_registry

registry = build_default_registry()
strategy = registry.create("S008", lookback=10)
```

Demo entrypoint (breakout-oriented, not the primary research spine):

```bash
python main.py
```

---

## Testing

```bash
python -m unittest discover -s tests -v
```

---

## Adding a strategy

1. Follow [research/README.md](research/README.md) (hypothesis first).
2. Add a `BaseStrategy` subclass under `strategies/` with `strategy_id`, `strategy_name`, `description`.
3. Implement `generate_signals(self, candles: Sequence[Bar]) -> list[Signal]`.
4. Add tests; run the suite above.

Engineering expectations: [PRINCIPLES.md](PRINCIPLES.md).  
What exists today: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).
