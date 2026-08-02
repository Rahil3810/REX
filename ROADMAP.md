# ROADMAP

**Purpose:** Define where REX is going, what is in focus, and what is deferred.  
**Audience:** Maintainers planning work; contributors aligning scope.  
**Owner:** Project Maintainer  
**Update Frequency:** Often (when priorities or milestones change)  
**Last Reviewed:** 2026-07-23  
**Related Documents:** [VISION.md](VISION.md) · [PRINCIPLES.md](PRINCIPLES.md) · [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · [README.md](README.md)

---

## Status Legend

| Label | Meaning |
|-------|---------|
| **Implemented** | Exists in the repository and is usable |
| **In Progress** | Active current focus |
| **Planned** | Intended in a named phase; not built yet |
| **Deferred** | Intentionally postponed |
| **Rejected** | Considered and declined (see Decision Log) |

---

## Current Focus

**Phase 1 — Research Integrity** (In Progress)

Make every advertised research contract true: finish or remove incomplete execution/lifecycle behavior, stop documenting fiction, and establish honest baselines before expanding strategy count or realism.

See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for what is true in the codebase today.

---

## Phases

### Phase 1 — Research Integrity

**Status:** In Progress  

**Goal:** Ensure the research kernel’s claims match its behavior.

**Why it matters:** Unfinished contracts (for example expiry accounting without expiry logic) produce false confidence. Integrity must precede discovery volume.

**Deliverables (Planned):**
- Pending-plan expiry via `timeout_candles` → `EXPIRED` — **Done** (CTX-009)
- Make `EntryModel` honest (implement LIMIT/STOP or remove unimplemented values)
- Document signal-study vs trade-simulation modes explicitly in usage docs
- Reduce dual-orchestration confusion (`SignalEngine` vs `BacktestRunner`) via docs and/or thin adapter work
- Quarantine or remove empty placeholder strategies/rules from the “capability” narrative

**Exit Criteria:**
- No public lifecycle reason or entry mode exists without a producing code path and tests
- README and PROJECT_CONTEXT agree on research modes and current strategies
- Default trade path does not silently imply support for strategies the policy rejects without clear reporting

---

### Phase 2 — Research Infrastructure

**Status:** Planned  

**Goal:** Make the kernel strategy-agnostic, provenance-aware, and safe for multi-year experiments.

**Why it matters:** Without agnostic execution translation and experiment identity, adding strategies multiplies special cases and irreproducible results.

**Deliverables (Planned):**
- Per-strategy `TradeSetupFactory` implementations; keep kernel free of signal-type switches
- Experiment / result provenance (dataset identity, parameters, policy/fill versions)
- Warm-up / bounded history contract on the strategy interface, enforced by the runner
- Instrument/symbol specifications; remove hardcoded symbol allowlists where config should own them
- Single research entrypath as the spine (BacktestRunner-centric)
- Paper/live executors consuming the same `TradePlan` type

**Exit Criteria:**
- A new non-sweep strategy can be trade-simulated without editing kernel policy switches
- A `BacktestResult` (or companion artifact) records enough identity to reproduce a run
- Strategies declare lookback needs; runner does not rely on unbounded full-history scans as the only pattern

---

### Phase 3 — Strategy Discovery

**Status:** Planned  

**Goal:** Expand the catalog of real, hypothesis-backed strategies on the honest substrate.

**Why it matters:** The platform’s purpose is discovering strategies—but only after the lab is trustworthy.

**Deliverables (Planned):**
- Additional strategies with written hypotheses under `research/`
- Reuse of tested rules (compose, don’t copy)
- Removal or strict quarantine of no-op catalog placeholders
- Trade-sim-aware comparison and parameter sweeps that write provenance

**Exit Criteria:**
- Multiple non-placeholder strategies with documented hypotheses and tests
- Comparison runs can use trade simulation where the hypothesis requires it
- No empty rule/strategy modules presented as features

---

### Phase 4 — Validation

**Status:** Planned  

**Goal:** Institutionalize out-of-sample and robustness evaluation.

**Why it matters:** In-sample expectancy alone is not acceptance. Validation is how REX avoids self-deception.

**Deliverables (Planned):**
- Written validation protocol (train/validate or walk-forward conventions)
- Session/regime slice reporting where relevant
- Clear “accepted / rejected / inconclusive” experiment outcomes in research notes

**Exit Criteria:**
- No strategy is marked accepted without held-out or walk-forward evidence per protocol
- Research notes consistently record rejection criteria and outcomes

---

### Phase 5 — Paper Trading

**Status:** Planned (distant)  

**Goal:** Run accepted strategies against a live or delayed data clock without real capital, using the same strategy contracts as research.

**Why it matters:** Surfaces operational issues (data gaps, session boundaries, state) before capital risk.

**Deliverables (Planned):**
- Thin paper adapter over the shared strategy interface
- Parity checks: paper behavior vs backtest assumptions is explicit

**Exit Criteria:**
- Paper path uses the same `generate_signals` contract as backtests
- Divergences from backtest assumptions are documented, not silent

**Dependency:** Phases 1–4 exit criteria met for any strategy promoted to paper.

---

### Phase 6 — Live Trading

**Status:** Planned (last)  

**Goal:** Optional thin live execution boundary for strategies that survived validation and paper.

**Why it matters:** Capital deployment is a product decision, not the research platform’s primary purpose.

**Deliverables (Planned):**
- Explicit risk controls and kill switches
- Broker/adapter isolation from strategy logic

**Exit Criteria:**
- Research remains the source of truth for strategy logic
- Live layer does not fork strategy implementations

**Dependency:** Successful paper trading for the same strategy contract.

---

## Completed Milestones

| Milestone | Status |
|-----------|--------|
| Causal chronological `BacktestRunner` | Implemented |
| `BaseStrategy` + registry discovery | Implemented |
| Dukascopy historical download / parse / store / provider (M1) | Implemented |
| Zone breakout strategy (signal research) | Implemented |
| Liquidity Sweep (S008) + rule composition pattern | Implemented |
| Trade simulation v1 (`FillModel`, `TradeSimulator`) | Implemented |
| Shared execution layer (`TradeSetup` / `TradePlan` / factory / validator / planner) | Implemented |
| Pending TradePlan expiry (`timeout_candles` → `EXPIRED`) | Implemented |
| Performance metrics + result export (JSON/CSV/Excel) | Implemented |
| Signal and execution lifecycle reconciliation helpers | Implemented |
| Market structure analyzer (analysis-only) | Implemented |
| Comprehensive automated test suite | Implemented |
| Documentation system (VISION / PRINCIPLES / ROADMAP / PROJECT_CONTEXT) | Implemented |

---

## Deferred Work

Explicitly postponed (not near-term phases):

- Portfolio / multi-position netting and book-level simulation
- Full event-sourced rewrite of the bar loop
- Multi-broker / multi-exchange connectivity
- AI-assisted strategy generation or automated search agents
- Premature indicator “platform” frameworks
- Parquet-only data lake / distributed backtest cluster
- Cloning LEAN/Nautilus module layouts

---

## Future Ideas

Non-committed ideas (may move to Planned, Deferred, or Rejected):

- Richer fill models (spread, slippage sensitivity reports)
- Multi-timeframe synchronized decision context
- Dataset checksum / schema version embedded in results
- Research notebooks for exploration (not as source of truth)
- DST-aware session calendars

---

## Research Questions

These are **scientific questions**, not implementation tasks. Engineering work should help answer them—not replace them.

1. Does Liquidity Sweep outperform Zone Breakout under comparable, documented execution assumptions?
2. Which sessions (if any) provide a statistical edge for a given strategy family?
3. Does adding market-structure filters improve expectancy, or only reduce trade count?
4. Does multi-timeframe confirmation improve robustness across years?
5. How sensitive are results to fill assumptions (ambiguity policy, spread, entry delay)?
6. What minimum sample size is required before a hypothesis is decision-ready?
7. Do parameter choices stable on one year remain stable on held-out years?

Hypothesis notes belong under `research/`. Process howto: [research/README.md](research/README.md).

---

## Decision Log

### ROAD-001

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Phase 1 named Research Integrity |
| **Status** | Accepted |
| **Decision** | Call Phase 1 **Research Integrity** (not “Research Honesty” or “Research Foundation”). |
| **Reason** | “Integrity” emphasizes claimed contracts matching behavior. “Foundation” undersells the existing kernel and sounds like greenfield work. |
| **Alternatives Considered** | Research Honesty; Research Foundation. |
| **Consequences** | Current Focus and Phase 1 headings use this name. |

### ROAD-002

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Paper and live trading are last |
| **Status** | Accepted |
| **Decision** | Phases 5–6 remain distant and gated on Phases 1–4. |
| **Reason** | Aligns with vision: research quality before capital path. |
| **Alternatives Considered** | Parallel live prototype early. |
| **Consequences** | Live/broker work before integrity/provenance is out of scope. |

### ROAD-003

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Separate Research Questions from deliverables |
| **Status** | Accepted |
| **Decision** | Roadmap maintains an explicit Research Questions section distinct from Planned features. |
| **Reason** | Prevents confusing scientific goals with engineering tickets. |
| **Alternatives Considered** | Mix questions into phase deliverables. |
| **Consequences** | New hypotheses are added here or in `research/`; they do not silently become platform features. |

### ROAD-005

| Field | Value |
|-------|-------|
| **Date** | 2026-07-23 |
| **Title** | Shared execution layer foundation |
| **Status** | Accepted |
| **Decision** | Ship `execution/` (factory, validator, policy, sizer, planner) with `TradeSetup` / `TradePlan` before paper/live. Strategies remain Signal-only. |
| **Reason** | Unblocks strategy-agnostic planning and future executors without cloning commercial engines. |
| **Alternatives Considered** | Keep Signal→pending-order translation inside `backtests/` only. |
| **Consequences** | Phase 2 focuses on more factories, provenance, and later paper/live adapters over the same `TradePlan`. |
