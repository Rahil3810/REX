# PRINCIPLES

**Purpose:** Non-negotiable engineering constitution for REX.  
**Audience:** Contributors, reviewers, and AI assistants modifying the codebase.  
**Owner:** Project Maintainer  
**Update Frequency:** Rarely (add or amend only with explicit decision)  
**Last Reviewed:** 2026-07-20  
**Related Documents:** [VISION.md](VISION.md) · [ROADMAP.md](ROADMAP.md) · [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · [README.md](README.md)

---

## Repository Philosophy

The repository should remain understandable by a **single engineer**.

When complexity exceeds understanding, **simplify before adding abstractions**.

Prefer understanding over cleverness. Prefer boring, explicit code over clever indirection.

Infrastructure exists to accelerate research—not to become the project.

---

## Principles

### 1. No lookahead bias

**Rule:** Strategies and outcome rules may use only information available at the decision time. Replay never exposes future candles as if they were known.

**Explanation:** The runner feeds chronological, completed bars. Strategies must not peek beyond the current bar index. Outcome and fill logic must respect causal order (for example, next-bar entry after signal bar).

**Why it exists:** Lookahead produces fictional edge. Undetected lookahead destroys the entire research program.

---

### 2. Honest simulations

**Rule:** Document and implement only the execution assumptions you actually apply. Do not imply fills, expiry, slippage, or sizing that the code does not perform.

**Explanation:** Conservative OHLC fills, ambiguity handling, and R-multiple P&amp;L are research assumptions. Incomplete APIs (for example declared but unimplemented entry modes) must be fixed or removed—not left as silent no-ops.

**Why it exists:** Optimistic or incomplete simulation creates false confidence and invalid strategy ranking.

---

### 3. Reproducibility

**Rule:** A reported result must be reconstructible from recorded inputs: data identity, strategy identity and parameters, policy/fill versions, and code version when available.

**Explanation:** Today provenance tooling is incomplete; the obligation still stands. Do not claim performance without preserving enough context to rerun the experiment.

**Why it exists:** Irreproducible “wins” are anecdotes, not research.

---

### 4. Scientific thinking

**Rule:** Treat every strategy as a hypothesis with explicit conditions, outcome definition, metrics, sample expectations, and rejection criteria.

**Explanation:** Chart intuition is allowed only as hypothesis generation. Tuning after seeing results requires a new experiment version. Negative results are first-class outcomes.

**Why it exists:** Without falsifiability, the platform becomes a storytelling engine.

---

### 5. Simplicity over complexity

**Rule:** Choose the simplest design that correctly solves the present research problem.

**Explanation:** Do not add event buses, portfolio layers, broker abstractions, or indicator frameworks “for later” without a concrete need.

**Why it exists:** Complexity compounds faster than research value. See also Repository Philosophy above.

---

### 6. Every abstraction solves a real problem

**Rule:** Introduce an interface, layer, or package only when it removes duplication, enforces a boundary, or unlocks a measured research need.

**Explanation:** Protocols such as `FillModel` earn their keep when fill assumptions must vary. Empty placeholder modules and unused “future” rules do not.

**Why it exists:** Premature abstraction obscures ownership and invites drift from reality.

---

### 7. Strategy-agnostic infrastructure

**Rule:** The backtest kernel must not hardcode strategy-specific signal taxonomies or execution rules into shared orchestration.

**Explanation:** Strategies (or strategy-owned policies) define how signals become setups. Shared runners, simulators, and metrics remain generic. Violations are technical debt to remove, not patterns to extend.

**Why it exists:** A kernel coupled to one strategy family cannot host an open research catalog.

---

### 8. Clear separation of concerns

**Rule:** Rules detect; strategies orchestrate; backtests simulate and measure; historical code loads data; models carry data—not business sprawl.

**Explanation:** Rules must not import backtests. Analysis-only components must not silently emit trade decisions. Live/demo coordinators must not own a single hardwired strategy forever.

**Why it exists:** Tangled ownership makes causality and testing unverifiable.

---

### 9. Explicit over implicit

**Rule:** Prefer named modes, parameters, and return values over hidden defaults that change scientific meaning.

**Explanation:** Signal-frequency studies and trade-simulation studies are different experiments. Overlap policies, ambiguity P&amp;L, and timeouts must be visible in results or configuration—not tribal knowledge.

**Why it exists:** Implicit behavior produces irreproducible comparisons.

---

### 10. Testability of claimed behavior

**Rule:** Behavior advertised by APIs, docs, or accounting fields must be covered by tests. Do not expose lifecycle states the simulator cannot produce.

**Explanation:** If results count `EXPIRED` setups, the simulator must be able to expire them—or the field must not exist.

**Why it exists:** Tests that certify fiction are worse than missing tests.

---

### 11. Maintainability and long-term thinking

**Rule:** Optimize for the engineer who maintains this code in three years—including you.

**Explanation:** Prefer modifying existing focused modules over parallel systems. Preserve backward compatibility when practical; when breaking, update docs and tests in the same change.

**Why it exists:** Research programs outlive feature spikes.

---

### 12. Build only what creates research value

**Rule:** Reject work that does not improve hypothesis evaluation, honesty, reproducibility, or validation discipline—unless it is required maintenance.

**Explanation:** Aligns engineering effort with [VISION.md](VISION.md). Paper/live trading come after the research lab is trustworthy.

**Why it exists:** Prevents platform sprawl.

---

### 13. Documentation evolves with code

**Rule:** When behavior or architecture changes materially, update the owning document in the same effort.

**Explanation:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) tracks current state. [ROADMAP.md](ROADMAP.md) tracks direction. Do not leave aspirational text looking like implementation.

**Why it exists:** Drift turns docs into liabilities.

---

### 14. One source of truth

**Rule:** Each concept lives in exactly one document or module; others reference it.

**Explanation:** Vision → `VISION.md`. Rules → `PRINCIPLES.md`. Current state → `PROJECT_CONTEXT.md`. Plans → `ROADMAP.md`. Usage → `README.md`.

**Why it exists:** Duplication guarantees contradiction.

---

## Decision Log

### PRIN-001

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Strategy-agnostic infrastructure is constitutional |
| **Status** | Accepted |
| **Decision** | Shared backtest/execution code must not special-case individual strategies’ signal types. Current sweep-specific default policy is debt, not design. |
| **Reason** | Matches vision: platform for many strategies. |
| **Alternatives Considered** | Allow kernel `if signal_type` switches per strategy family. |
| **Consequences** | New strategies should bring or register their own execution translation; kernel edits for signal enums are a smell. |

### PRIN-002

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Incomplete contracts are forbidden |
| **Status** | Accepted |
| **Decision** | Public models and accounting must not advertise states or entry modes the runtime cannot produce. Fix or remove. |
| **Reason** | False completeness misleads research and tests. |
| **Alternatives Considered** | Leave TODOs in models “for later.” |
| **Consequences** | Phase 1 roadmap work includes expiry/entry-model honesty. |

### PRIN-003

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Single-engineer understandability |
| **Status** | Accepted |
| **Decision** | Complexity that exceeds one maintainer’s mental model must be simplified before further abstraction. |
| **Reason** | Small-team research lab reality. |
| **Alternatives Considered** | Grow framework surface toward commercial engines. |
| **Consequences** | Large proposals require a complexity justification tied to research value. |
