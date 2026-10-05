# PROJECT_CONTEXT

**Purpose:** Describe the **current** state of the REX repository for contributors and AI assistants.  
**Audience:** Developers and AI assistants working in this codebase.  
**Owner:** Project Maintainer  
**Update Frequency:** Frequently (whenever architecture, capabilities, or debt change)  
**Last Reviewed:** 2026-08-02  
**Related Documents:** [VISION.md](VISION.md) · [PRINCIPLES.md](PRINCIPLES.md) · [ROADMAP.md](ROADMAP.md) · [README.md](README.md) · [research/README.md](research/README.md)

> Why we exist, engineering rules, and future phases are **not** redefined here. See the related documents above.

---

## Product

**REX** is a quantitative trading **research** platform.  
It does **not** place live broker orders today.

Repository directory name may still be `forex-bot` (historical). Product name in documentation is **REX**.

---

## Active Milestone

**Phase 1 — Research Integrity** (see [ROADMAP.md](ROADMAP.md)).

Focus: make advertised execution/lifecycle contracts match implementation; keep docs honest; reduce dual-path confusion.

The shared **execution layer** (`execution/`) is now in place so future paper/live executors can reuse planning without changing strategies.

---

## Current Architecture

### Detection → planning → execution

```text
Bars
  → Strategy.generate_signals → Signal          # detection only
  → TradeSetupFactory → TradeSetup              # opportunity (hints only)
  → TradeSetupValidator                         # structural gate (extend here)
  → TradePlanner
        ├─ ExecutionPolicy → prices / expiry
        └─ PositionSizer → size / risk amount
  → TradePlan (status=PLANNED)
  → TradeSimulator + FillModel                  # backtest executor
  → Position / ClosedTrade / TerminatedSetup
  → PerformanceMetrics → BacktestResult
```

Strategies must **not** compute position size, account risk, margin, or broker details. Those belong in `execution/`.

**Primary research spine:** `BacktestRunner` in `backtests/`.

**Secondary demo path:** `SignalEngine` in `core/` — currently hardwired to `BreakoutStrategy`. Prefer `BacktestRunner` for research.

**Feature spine (Phase 1 architecture):** `FeatureRepository` in `core/features/` materializes immutable `FeatureContext` packs. Views (`TrendView`, `MomentumView`, `VolatilityView`, `PhaseView`) are pure projections with required `method_id`. Strategies do **not** yet consume `FeatureContext` (Phase 2). Legacy `ChartAnalyzer` remains for demo zone enrichment only.

### Execution component responsibilities

| Component | Responsibility | Extension point |
|-----------|----------------|-----------------|
| `TradeSetupFactory` | `Signal` → `TradeSetup` | `SweepTradeSetupFactory` today; add breakout/etc. factories later |
| `TradeSetupValidator` | Minimal structural validation before planning | Expand here — do **not** scatter validation into planner/policy/sizer/executor |
| `ExecutionPolicy` | Entry model, SL, TP, timeout from setup hints | `FixedRiskRewardPolicy` today; may later split into Entry/Stop/Target/Expiry policies (docs only — not implemented) |
| `PositionSizer` | Size + risk amount from `AccountContext` | `FixedRiskSizer` today |
| `TradePlanner` | Thin orchestrator → `TradePlan` | Swap policy/sizer via constructor |
| `TradeSimulator` | Backtest executor consuming `TradePlan` | Future paper/live executors share `TradePlan` |

Domain notes:

- Directions use `TradeDirection` (`LONG` / `SHORT`), not raw strings.
- `TradePlan.planned_at` records when the plan was produced (causal bar time in backtests). Execution timestamps are not modeled yet.
- `AccountContext` stays minimal (`equity`, `risk_fraction`) so a future Portfolio can compose it without breaking constructors.

---

## Folder Structure

| Path | Responsibility |
|------|----------------|
| `models/` | Pure domain data (`Bar`, `Signal`, `TradeDirection`, `TradeSetup`, `TradePlan`, positions, results) |
| `execution/` | Shared planning layer (factory, validator, policy, sizer, planner) |
| `strategies/` | `BaseStrategy`, registry, concrete strategies |
| `strategies/rules/` | Reusable detection rules (no backtest imports) |
| `backtests/` | Replay, trade simulator (executor), fills, metrics, results, comparison |
| `historical/` | Dukascopy download, parse, storage, provider |
| `core/` | Config/zone loaders, feeds, sessions, chart context, signal engine, feature architecture |
| `core/zones/` | `ZoneEngine` + `ZoneProvider` (manual HTF supply/demand today) |
| `core/indicators/` | `IndicatorEngine` + `IndicatorProvider` (pandas-ta-classic behind `PandasTAProvider`) |
| `core/market/` | Thin `Market` + `Instrument` metadata (capabilities, calendar boundary) |
| `core/features/` | `FeatureRepository`, `FeatureContext`, feature packs, generators, Views |
| `config/` | JSON configuration files |
| `data/historical/` | Generated yearly M1 CSV partitions (runtime data) |
| `research/` | Observations, hypotheses, experiment notes |
| `tests/` | Automated tests (`unittest`) |
| `docs/archive/` | Retired documentation snapshots (not maintained) |
| `examples/`, `notebooks/` | Placeholders; not part of the supported research path |
| `logs/` | Runtime logs |

---

## Major Modules

### Strategies

| ID / Name | Status | Notes |
|-----------|--------|-------|
| `CORE_ZONE_BREAKOUT` (`BreakoutStrategy`) | Implemented | Zone interaction signals; stateful; used by `SignalEngine` |
| `S008` (`LiquiditySweepStrategy`) | Implemented | Thin orchestrator over `LiquiditySweepRule`; trade mode via `SweepTradeSetupFactory` |
| `S001`–`S006` (`experiments.py`) | Placeholder | Registered; emit no signals |
| `BOSRule`, `RetestRule` | Implemented rules, unused by strategies | Not strategy-complete features |
| `MomentumRule`, `SessionRule` | Empty stubs | Not features |

### Execution layer (`execution/`)

| Module | Role |
|--------|------|
| `SweepTradeSetupFactory` | Default factory: sweep signals → `TradeSetup` |
| `TradeSetupValidator` | Minimal structural gate (architectural boundary) |
| `FixedRiskRewardPolicy` | Default `ExecutionPolicy` (hints → SL/TP/R/timeout) |
| `FixedRiskSizer` | Default `PositionSizer` (equity × risk fraction) |
| `TradePlanner` | Orchestrates policy + sizer → `TradePlan` |

### Backtesting

| Module | Role |
|--------|------|
| `BacktestRunner` | Causal bar replay; wires factory → validator → planner → simulator |
| `TradeSimulator` | Backtest executor: pending `TradePlan` → open → closed/terminated |
| `ConservativeOHLCFillModel` / `FillModel` | OHLC fill assumptions (does not apply estimated fees/spread yet) |
| `PerformanceMetrics` | Signal-outcome or trade P&amp;L metrics (R-multiples) |
| `BacktestResult` | Results + lifecycle reconciliation helpers + export |
| `StrategyComparison` | Sequential multi-strategy runs (signal-study oriented by default) |

### Historical data

| Module | Role |
|--------|------|
| `HistoricalDownloader` | Invokes `duka`, retries, yearly partitions |
| `HistoricalDataParser` | Strict CSV → `Bar` |
| `HistoricalStorage` | Atomic yearly files + meta |
| `HistoricalDataProvider` | `get_bars(symbol, timeframe, start, end)` — M1 today |

### Core services

| Module | Role |
|--------|------|
| `SignalEngine` | Demo coordinator; **breakout-only** today |
| `ChartAnalyzer` / `signal_enricher` | Zone-relative context on signals (legacy path; still used) |
| `ZoneEngine` (`core/zones/`) | Reusable zone queries via `ZoneProvider`; Strategy V1 HTF filter |
| `ManualZoneProvider` | Loads trader-defined zones from `config/zones.json` / `ZoneBook` |
| `IndicatorEngine` (`core/indicators/`) | Library-agnostic TA API; delegates to `IndicatorProvider` |
| `PandasTAProvider` | Sole adapter to `pandas-ta-classic` (`import pandas_ta_classic as ta`) |
| `Market` / `Instrument` (`core/market/`) | Domain vs tradeable metadata; pip/tick via Instrument; no asset-class packages |
| `TradingCalendar` | Boundary only (`AlwaysOpenCalendar`); FX sessions still in `SessionManager` |
| `FeatureRepository` (`core/features/`) | In-memory materializer → immutable `FeatureContext` packs |
| Feature packs / generators | Price, structure (swings), volatility (range expansion), indicators, zones, session |
| Views (`TrendView`, `MomentumView`, `VolatilityView`, `PhaseView`, `LiquidityView`) | Pure projections; require `method_id`; no detection |
| `SessionManager` | Fixed UTC session windows (DST not modeled) |
| `DataFeed` / `MockDataFeed` | Feed abstraction; mock for demos/tests |

**Note:** Dual MSA / Strategy-V1 placeholder stacks were removed (CTX-013). Trend is a View (`market_structure_v1`); body-size classification is `RangeExpansion` on `VolatilityPack`, not momentum. Strategies still call `generate_signals(candles)` until Phase 2 wires `FeatureContext`.

---

## Current Capabilities

**Implemented and usable:**

- Chronological, causal strategy replay (`BacktestRunner`)
- Per-symbol history isolation during replay
- Strategy registry auto-discovery
- Dukascopy-backed M1 historical pipeline
- Signal-frequency studies (no outcome provider → counts only)
- Optional trade simulation with conservative OHLC fills, ambiguity handling, R-multiple P&amp;L
- Lifecycle reconciliation helpers on `BacktestResult`
- Result export: JSON, CSV, Excel
- FeatureRepository materialization + versioned Views (no platform confidence integer)
- Session labeling helpers
- Automated test suite (`unittest`)

**Research modes (explicit):**

1. **Signal study** — `simulate_trades=False`; optional `outcome_provider` for custom realized outcomes.
2. **Trade simulation** — `simulate_trades=True`; pipeline factory → validator → planner → `TradeSimulator` + `FillModel`.

These answer different questions. Do not mix their metrics casually.

---

## Current Limitations

Be precise when researching:

- Default `SweepTradeSetupFactory` only handles `BULLISH_SWEEP` / `BEARISH_SWEEP`. Other signal types never become setups (counted as rejected at the boundary), not “failed strategies.”
- `TradePlanStatus` defines QUEUED/ACTIVE/CLOSED/CANCELLED/EXPIRED; backtests only emit **PLANNED** today (status field is not mutated — deferred until paper/live; see CTX-008).
- `TradePlan.estimated_fees` / `estimated_spread` / `estimated_slippage` exist but are **not applied** by the OHLC fill model.
- Pending-plan `timeout_candles` is enforced (`EXPIRED`); open-position hold uses separate `max_hold_candles`.
- `EntryModel.LIMIT` and `STOP` are declared; fill model only implements `NEXT_CANDLE_OPEN` (unfilled LIMIT/STOP expire or cancel at end-of-data).
- Negative / non-physical prices are not fully policed in the execution layer (see CTX-007); research relies on historical OHLC validation.
- `SignalEngine` is not registry-driven and is not the research spine.
- `Signal` remains zone-oriented (`zone_id` required; non-zone strategies use `0`).
- Backtest symbol allowlist comes from ``Instrument.research_enabled`` via ``research_symbols()``.
- Full bar list is materialized and sorted in memory per run.
- Strategies receive growing full history each bar (bounded windowing is strategy-local convention today).
- No experiment provenance (dataset hash, config checksum, versions) embedded in results yet.
- Session windows ignore DST.
- One active trade lifecycle per `(strategy_id, symbol)` — additional signals ignored while active.
- Ambiguity exits force `-1R` by current policy.
- `examples/` and `notebooks/` are not supported entrypoints.

---

## Known Technical Debt

| Item | Severity | Notes |
|------|----------|-------|
| LIMIT/STOP fills unimplemented | Medium | Plans wait then EXPIRED / cancel |
| Price sanity beyond OHLC shape (DEF-003) | Medium | Deferred — CTX-007 |
| `TradePlanStatus` not mutated in backtest | Low–Medium | Deferred until paper — CTX-008 |
| Sweep-only default `TradeSetupFactory` | Medium | Add factories per strategy family |
| Dual orchestration (`SignalEngine` vs runner) | High | Confuses contributors |
| Placeholder strategies S001–S006 | Medium | Catalog noise |
| Empty Momentum/Session rules | Medium | False capability signal |
| Unused BOS/Retest rules without strategy wiring/tests | Medium | Orphan logic |
| Zone-centric universal `Signal` | Medium | Hurts non-zone strategies |
| Hardcoded symbol allowlists | Low | Largely addressed — allowlist from `research_symbols()`; config lists remain data |
| No result provenance | Medium | Phase 2 |
| Cost fields unused in fills | Medium | Apply when realism milestone lands |
| DST-unaware sessions | Low–Medium | Affects session research |
| In-memory full-dataset sort | Low–Medium | OK for current scale |
| Orphaned market structure vs strategies | Low | Intentional analysis-only for now |

Retired gap snapshot (historical only): [docs/archive/GAP_ANALYSIS_2026_PRE_DOCUMENTATION_REFRESH.md](docs/archive/GAP_ANALYSIS_2026_PRE_DOCUMENTATION_REFRESH.md).

---

## Coding Conventions

- Prefer composition: rules hold detection logic; strategies orchestrate.
- Type hints and focused docstrings on public APIs.
- Keep strategies thin; avoid duplicating rule logic.
- Do not import `backtests` from `strategies/rules`.
- Match existing style in the touched package; no drive-by refactors.
- Tests required for important behavior changes; run `python -m unittest discover -s tests -v`.
- Engineering rules: [PRINCIPLES.md](PRINCIPLES.md).

---

## Repository Conventions

- Product name in docs: **REX**.
- Strategy modules under `strategies/` with non-empty `strategy_id`, `strategy_name`, `description`.
- Config in `config/*.json`; do not hardcode operational settings when a loader exists.
- Research evidence and hypotheses under `research/` (see [research/README.md](research/README.md)).
- Living docs: update the **owning** document when behavior changes (see One source of truth in PRINCIPLES).
- Do not resurrect archived docs as living sources of truth.

---

## AI Assistant Guidance

When working in this repository:

1. Read [VISION.md](VISION.md), [PRINCIPLES.md](PRINCIPLES.md), [ROADMAP.md](ROADMAP.md), and **this file** before large changes.
2. Prefer extending `BacktestRunner` / `execution/` over growing `SignalEngine`.
3. Do not invent features in documentation or code comments.
4. Do not add placeholder strategies/rules “for later.”
5. Do not implement paper/live trading, portfolio engines, or broker adapters unless the roadmap focus explicitly calls for them.
6. New strategy families that need trade simulation: add a `TradeSetupFactory`, not kernel `if signal_type` switches.
7. Extend `TradeSetupValidator` for opportunity rules; do not push that validation into `TradePlanner`.
8. If fixing integrity gaps (expiry, EntryModel, cost application), update PROJECT_CONTEXT and ROADMAP in the same change.
9. Search the repo for existing components before creating new packages.
10. Challenge designs that only work for one strategy.

---

## Things Contributors Should Avoid

- Copying LEAN/Nautilus/Backtrader architecture wholesale
- Hardcoding new strategy signal types into shared kernel switches
- Presenting empty modules as capabilities
- Claiming win rate / expectancy without defined outcomes or trade simulation
- Mixing signal-study metrics with trade-sim metrics without disclosure
- Large unrelated refactors in strategy research PRs
- Adding dependencies without a clear research need
- Updating aspirational docs instead of PROJECT_CONTEXT when reality changes

---

## Future Direction

Short pointer only: [ROADMAP.md](ROADMAP.md).

Next: finish Phase 1 (Research Integrity), then Phase 2 (Research Infrastructure). Paper/live trading remain distant and gated.

---

## Decision Log

### CTX-001

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | PROJECT_CONTEXT is current-state only |
| **Status** | Accepted |
| **Decision** | This file no longer holds vision essays, principle lists, or multi-year feature mythology. Those live in VISION / PRINCIPLES / ROADMAP. |
| **Reason** | Previous PROJECT_CONTEXT mixed aspiration with as-built truth and drifted. |
| **Alternatives Considered** | Keep a single mega-doc. |
| **Consequences** | Contributors and AI tools must read the four-doc system; this file must stay factual. |

### CTX-002

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | BacktestRunner is the research spine |
| **Status** | Accepted |
| **Decision** | Document and treat `BacktestRunner` as the primary research entrypath; `SignalEngine` is a limited demo coordinator. |
| **Reason** | Dual paths caused incorrect assumptions about platform capability. |
| **Alternatives Considered** | Elevate SignalEngine to parity immediately. |
| **Consequences** | New research features attach to the runner/simulator path first. |

### CTX-003

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | GAP_ANALYSIS retired to archive |
| **Status** | Accepted |
| **Decision** | Living gap tracking lives in this file (limitations/debt) and ROADMAP (planned/deferred). |
| **Reason** | Stale GAP_ANALYSIS incorrectly denied the historical CSV stack. |
| **Alternatives Considered** | Maintain GAP_ANALYSIS as a fifth living doc. |
| **Consequences** | Archive file is historical only. |

### CTX-004

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | Separate detection, planning, and execution |
| **Status** | Accepted |
| **Decision** | Strategies emit `Signal` only. `TradeSetup` is the opportunity; `TradePlan` is executable; `execution/` owns factory, validator, policy, sizer, planner. `TradeSimulator` is the backtest executor consuming `TradePlan`. |
| **Reason** | Enables paper/live reuse without changing strategy code; removes sizing/risk from strategies. |
| **Alternatives Considered** | Expand old Signal→TradeSetup policy inside `backtests/`; force strategies to emit TradeSetup immediately. |
| **Consequences** | Old pending-order `TradeSetup` meaning retired. Runner uses factory→validator→planner. `risk_policy=` kwarg removed. |

### CTX-005

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | TradeSetupValidator is the validation boundary |
| **Status** | Accepted |
| **Decision** | Opportunity validation lives only in `TradeSetupValidator`. Planner/policy/sizer/executors assume a validated setup (fill-time SL vs entry checks remain executor concerns). |
| **Reason** | Prevents scattered validation and keeps the seam ready for richer rules. |
| **Alternatives Considered** | Validate inside TradePlanner or ExecutionPolicy. |
| **Consequences** | Future checks extend the validator, not the planner. |

### CTX-006

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | TradeDirection enum and TradePlan.planned_at |
| **Status** | Accepted |
| **Decision** | Use `TradeDirection` (`LONG`/`SHORT`) across setup/plan/position/closed/terminated models. Add `TradePlan.planned_at` (planning-time metadata only). Keep `AccountContext` unchanged in fields; document Portfolio composition path. Do not split `ExecutionPolicy` yet — document future Entry/Stop/Target/Expiry split only. |
| **Reason** | Type safety and paper/live readiness without behavioural change or speculative abstractions. |
| **Alternatives Considered** | Keep string directions; add wall-clock `datetime.now()` for planned_at; add margin fields to AccountContext; split ExecutionPolicy now. |
| **Consequences** | Comparisons use the enum; `planned_at` uses causal candle time in backtests; AccountContext remains two fields. |

### CTX-007

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | Where invalid prices should be rejected (DEF-003) |
| **Status** | Accepted |
| **Decision** | **Not now** for new execution-layer price validation. Primary boundary for bad market prices is **historical / bar ingestion** (`HistoricalDataParser`, `BacktestRunner._validate_bar`). Opportunity hint sanity may later belong in `TradeSetupValidator` once instrument specs exist. Do **not** put generic “price > 0” rules in `ExecutionPolicy` or the simulator. |
| **Reason** | Research data already passes OHLC shape checks; forex-positive assumptions are instrument-specific; stuffing price policy into ExecutionPolicy couples construction to data quality and is the wrong SRP. |
| **Alternatives Considered** | Reject negatives in TradeSetupValidator immediately; reject in ExecutionPolicy; reject in FillModel. |
| **Consequences** | DEF-003 remains an open risk for hand-built setups; Dukascopy research path stays the trusted input. Revisit with Instrument model. |

### CTX-008

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | TradePlanStatus placeholder until paper trading (DEF-004) |
| **Status** | Accepted |
| **Decision** | Leave `TradePlanStatus` as a forward-looking enum. Backtests keep `PLANNED` only and record outcomes via `ClosedTrade` / `TerminatedSetup`. Do not implement QUEUED/ACTIVE/CLOSED mutations until a paper/live executor needs them. |
| **Reason** | Status transitions are only useful when an executor owns live lifecycle; forcing them now would be speculative and churn frozen plans. |
| **Alternatives Considered** | Mutate status in TradeSimulator now; remove unused enum values. |
| **Consequences** | Paper milestone owns status machine; research accounting remains reconcile counters + terminated/closed records. |

### CTX-009

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | Enforce pending TradePlan.timeout_candles (DEF-002) |
| **Status** | Accepted |
| **Decision** | `TradeSimulator` expires unfilled pending plans after `timeout_candles` wait bars with reason `EXPIRED`. Deterministic candle counting; no wall clock. |
| **Reason** | The field already existed on `TradePlan`; ignoring it lied to research accounting. |
| **Alternatives Considered** | Remove timeout_candles; expire only at end-of-data. |
| **Consequences** | LIMIT/STOP plans that never fill terminate as EXPIRED; NEXT_CANDLE_OPEN still fills on first eligible bar before expiry. |

### CTX-010

| Field | Value |
|-------|-------|
| **Date** | 2026-07-25 |
| **Title** | Modular research engines for Strategy V1 (zones first) |
| **Status** | Accepted |
| **Decision** | Add independent packages under `core/` (`zones`, structure contracts, `liquidity`, `momentum`). Zone queries go through `ZoneEngine` + `ZoneProvider`; only manual HTF supply/demand is live. Structure/liquidity/momentum are contracts + inert placeholders. Do not restructure or replace `ChartAnalyzer` / existing `MarketStructureAnalyzer`. |
| **Reason** | Strategy V1 needs composable engines without coupling detection sources to consumers, and without a repository-wide rewrite. |
| **Alternatives Considered** | Fold ZoneEngine into ChartAnalyzer; implement BOS/CHoCH now; auto-detect zones. |
| **Consequences** | Future AI/ML zone providers plug in via `ZoneProvider`. Strategy code should depend on engine contracts, not loaders. Existing breakout/signal paths remain unchanged. |

### CTX-011

| Field | Value |
|-------|-------|
| **Date** | 2026-07-25 |
| **Title** | IndicatorEngine + Provider (pandas-ta-classic behind adapter) |
| **Status** | Accepted |
| **Decision** | Add `core/indicators/` mirroring ZoneEngine: `IndicatorEngine` → `IndicatorProvider` → `PandasTAProvider`. Only the provider imports `pandas_ta_classic`. SMA/EMA/RSI/ATR/MACD/Bollinger/ADX are wrapped; no strategy/execution/backtest changes. |
| **Reason** | Standard TA math is not REX's edge; isolating the library keeps Momentum/Trend/Decision engines swappable and library-agnostic. |
| **Alternatives Considered** | Call pandas-ta from strategies; hand-roll indicators; use unmaintained `pandas-ta`. |
| **Consequences** | `pandas` / `pandas-ta-classic` are project dependencies. Public API returns `pd.Series` or typed result models (`MACDResult`, `BollingerBands`, `ADXResult`). |

### CTX-012

| Field | Value |
|-------|-------|
| **Date** | 2026-08-01 |
| **Title** | Thin Market + Instrument metadata (no multi-asset folders) |
| **Status** | Accepted |
| **Decision** | Add `core/market/` with `Market` (domain defaults) and `Instrument` (symbol metadata + capabilities). Pip sizes and backtest allowlist derive from the instrument catalog. Evidence placeholders take `analyze(bars, instrument)`. No forex/stocks/crypto/futures packages. |
| **Reason** | Remove hardcoded pip/symbol maps without pretending multi-market support exists. |
| **Alternatives Considered** | MarketAdapter hierarchy; per-asset-class placeholder packages; leaving pip maps in chart_analyzer. |
| **Consequences** | Register new symbols via `Instrument` instead of editing `_PIP_SIZES`. `SessionManager` remains the FX mega-session implementation behind `SessionFamily.FOREX_MEGA`. |

### CTX-013

| Field | Value |
|-------|-------|
| **Date** | 2026-08-02 |
| **Title** | FeatureRepository spine replaces dual Trend/Momentum stacks |
| **Status** | Accepted |
| **Decision** | Introduce in-memory `FeatureRepository` → `FeatureContext` (typed feature packs) → pure Views with required `method_id`. Port swings and body-size logic once (range expansion). Delete `MarketStructureAnalyzer`, ConfidenceCalculator, Strategy V1 Placeholder* engines, and `core/momentum` / `core/liquidity` placeholders. No platform confidence integer. Strategies still use `generate_signals(candles)` in Phase 1. |
| **Reason** | One canonical implementation per concept; decade-ready pack/view extensibility without engine-per-noun sprawl. |
| **Alternatives Considered** | Keep MSA as shim; persistent feature store; silent default trend method. |
| **Consequences** | Research structure/momentum tests target FeatureRepository/Views. SMC dialects are future optional packs, not core ontology. ChartAnalyzer demo path unchanged. |
