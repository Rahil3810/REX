# VISION

**Purpose:** Define why REX exists and what long-term success means.  
**Audience:** Maintainers, contributors, and anyone evaluating the project’s intent.  
**Owner:** Project Maintainer  
**Update Frequency:** Rarely (only when mission or identity materially changes)  
**Last Reviewed:** 2026-07-20  
**Related Documents:** [PRINCIPLES.md](PRINCIPLES.md) · [ROADMAP.md](ROADMAP.md) · [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) · [README.md](README.md)

---

## Mission

REX exists to systematically discover, validate, improve, and evolve statistically profitable trading strategies through rigorous quantitative research.

The software is a means. The end goal is a repeatable research process that continuously produces trustworthy strategy conclusions—including negative ones.

---

## Vision

In the long term, REX is a professional quantitative research laboratory:

- Strategies are hypotheses, not opinions.
- Backtests are experiments, not marketing demos.
- Results are reproducible and assumption-transparent.
- Infrastructure accelerates research without becoming the product.

REX is intentionally custom-built. Professional systems may be studied for engineering principles. Their implementations are not targets to clone.

---

## What REX Is

- A quantitative trading **research** platform.
- A causal historical replay and measurement system.
- A modular environment for composing market rules into strategies.
- A place where signal studies and (separately) trade-simulation studies can be run with explicit assumptions.
- A long-term codebase optimized for honesty, simplicity, and maintainability.

---

## What REX Is Not

- Not an auto-trading bot (today).
- Not a broker, exchange, or portfolio management product (today).
- Not a clone of QuantConnect LEAN, Nautilus Trader, Backtrader, Zipline, or any commercial platform.
- Not a feature race or framework popularity project.
- Not a substitute for scientific discipline.

---

## Core Values

1. **Honesty over optimism** — Prefer conservative, disclosed assumptions to flattering results.
2. **Research quality over feature count** — A smaller trustworthy lab beats a large unreliable platform.
3. **Simplicity over cleverness** — Prefer code a single engineer can fully understand.
4. **Evidence over narrative** — Charts inspire hypotheses; backtests decide.
5. **Negative results are progress** — Rejected ideas are valuable research outcomes.
6. **Infrastructure serves research** — Platform work must unlock better experiments, not exist for its own sake.

---

## Guiding Beliefs

- Data decides; the market is always correct relative to a tested claim.
- Every trading idea should become a measurable hypothesis.
- Every assumption should eventually become explicit and testable.
- Never optimize the platform for only one strategy.
- Long-term maintainability beats short-term convenience.
- Understanding every abstraction matters more than adopting fashionable architecture.

---

## Long-Term Objectives

At altitude—not as a feature checklist:

1. Make research conclusions reproducible across people, machines, and time.
2. Support many independent strategies and experiments without rewriting the kernel.
3. Keep execution assumptions honest, named, and swappable.
4. Establish validation discipline (out-of-sample / walk-forward thinking) before any live capital path.
5. Only then consider paper trading and live trading as thin adapters over the same research contracts.

Detailed phases live in [ROADMAP.md](ROADMAP.md). Current implementation state lives in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

---

## Success Definition

REX succeeds when the team can answer, with evidence:

- What was tested?
- Under which data, parameters, and execution assumptions?
- What would falsify the claim?
- Can another person reproduce the result?

A strategy is not “successful” because a short sample looks profitable. Success requires defined metrics, adequate sample size, stability across periods and conditions, and reproducible artifacts.

---

## Success Metrics

Primary indicators are **research quality**, not account profit:

| Metric | Intent |
|--------|--------|
| Reproducibility | Same inputs and versions yield the same outputs |
| Hypothesis throughput | Time from idea → measured result |
| Honest reporting rate | Assumptions, failures, and negatives recorded |
| Validation discipline | Held-out or walk-forward evidence before “accepted” |
| Robustness checks | Stability across sessions, regimes, or periods where relevant |
| Confidence in conclusions | Clarity about what is known vs unknown |

Financial P&amp;L may inform strategy evaluation. It is not the primary success metric of the **platform**.

---

## Non-Goals

REX intentionally does **not** optimize for:

- Maximum feature count or module inventory
- Being “another LEAN / Nautilus / Backtrader”
- Supporting every broker, exchange, or asset class early
- Becoming the largest open trading framework
- Premature portfolio, OMS, or multi-venue complexity
- Marketing appeal over engineering quality
- AI-generated strategies before experiment provenance is solid
- Abstractions that exist only to resemble professional engines

If a proposal increases complexity without improving research honesty or speed, it is out of scope.

---

## Decision Log

### VISION-001

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Official product name is REX |
| **Status** | Accepted |
| **Decision** | The product is named **REX**. “Forex Bot” may appear only as repository-path or historical reference. |
| **Reason** | Dual branding confused documentation and identity. |
| **Alternatives Considered** | Keep “Forex Bot”; dual-brand README and vision. |
| **Consequences** | All living docs use REX. Folder path may remain `forex-bot` until renamed separately. |

### VISION-002

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Software is means; research process is the end |
| **Status** | Accepted |
| **Decision** | Platform work is justified only when it improves the research process (speed, honesty, reproducibility, validation). |
| **Reason** | Prevents infrastructure theater. |
| **Alternatives Considered** | Treat REX as a general trading framework product. |
| **Consequences** | Roadmap prioritizes research integrity and infrastructure before paper/live trading. |

### VISION-003

| Field | Value |
|-------|-------|
| **Date** | 2026-07-20 |
| **Title** | Do not clone professional engines |
| **Status** | Accepted |
| **Decision** | Study LEAN/Nautilus/etc. for principles only; never treat feature parity as a goal. |
| **Reason** | Cloning creates complexity without understanding; contradicts the custom-build philosophy. |
| **Alternatives Considered** | Adopt an existing engine; mirror their module layout. |
| **Consequences** | Architecture proposals must cite a real REX research problem, not “LEAN has X.” |
