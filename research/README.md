# Strategy Research Process

**Purpose:** How to run the research workflow inside `research/`.  
**Audience:** Anyone forming or testing trading hypotheses in REX.  
**Related Documents:** [VISION.md](../VISION.md) · [PRINCIPLES.md](../PRINCIPLES.md) · [ROADMAP.md](../ROADMAP.md) · [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) · [README.md](../README.md)

Scientific rules (no lookahead, honest results, falsifiability) live in [PRINCIPLES.md](../PRINCIPLES.md). This file is the **howto** for notes and experiments in this folder.

---

## 1. Record observations

Store notes in the matching directory:

- `breakout_examples/` — clean breakout observations and screenshots
- `fake_breakouts/` — failed or reversed breakout observations
- `session_notes/` — behavior associated with named forex sessions
- `strategy_notes/` — hypotheses, definitions, changes, and conclusions

Each observation should record symbol, timeframe, candle timestamps and timezone, relevant zone IDs (if any), what was observed, and why it may be measurable. Record counterexamples as carefully as successful examples.

These directories may be empty until observations are added; empty folders are not evidence.

---

## 2. Store screenshots

Use PNG or JPEG and a deterministic name:

`YYYY-MM-DD_SYMBOL_TIMEFRAME_short-description.png`

Place screenshots beside a Markdown note with the same stem. Screenshots are evidence for forming a hypothesis; they are not backtest results. Never crop away timestamps, symbol, timeframe, or price scale when those details matter.

---

## 3. Define a hypothesis

Before implementation, create a strategy note containing:

- Strategy ID and one-sentence claim
- Exact signal conditions using completed candles only
- Required symbols, timeframes, zones, and sessions
- Data period and any exclusions
- Definition of a realized outcome **or** explicit trade-simulation assumptions
- Primary metric and minimum sample size
- Conditions that would reject the hypothesis

Do not tune a rule after seeing results without recording a new experiment version.

Open research questions (platform-level) are listed in [ROADMAP.md](../ROADMAP.md).

---

## 4. Test scientifically

Implement the hypothesis through `BaseStrategy.generate_signals(candles)`.

Replay with `BacktestRunner`:

- **Signal study** — measure frequency; supply an `outcome_provider` only when the experiment has an explicit, documented outcome rule using only candles available at that point.
- **Trade simulation** — set `simulate_trades=True` when the hypothesis defines entry/exit via the platform simulator. Confirm the execution policy understands your signal types (see [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md)).

The strategy must see only causal history (current completed candle and prior state). Export results and preserve enough context to reproduce the run (dataset range, parameters, mode). Separate exploratory and validation periods where possible.

A result with no realized outcomes and no closed trades can measure signal frequency but **cannot** support claims about win rate, expectancy, or profit factor.
