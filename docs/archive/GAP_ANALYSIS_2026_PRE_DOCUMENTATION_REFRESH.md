# ARCHIVED — Historical Snapshot

**Status:** No longer maintained.  
**Archived:** 2026-07-20  
**Reason:** Replaced by the living documentation system (`VISION.md`, `PRINCIPLES.md`, `ROADMAP.md`, `PROJECT_CONTEXT.md`).

This file is a **historical snapshot** of an earlier gap analysis. Several claims below were already outdated at archive time (notably the assertion that canonical historical CSV ingestion did not exist). Do not use this document as a source of truth.

Current limitations and debt: [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md)  
Planned and deferred work: [ROADMAP.md](../../ROADMAP.md)

---

# Gap Analysis

This review covers the current repository after adding the research and
backtesting infrastructure.

## Architectural weaknesses

1. **Signal outcomes are not part of existing strategy semantics.** The current
   breakout strategy detects zone interactions but defines no exit or realized
   return. The backtester therefore requires an experiment-specific outcome
   provider. Results without one are frequency studies, not performance tests.

2. **The existing signal engine and breakout state are in-memory.** A stopped
   run cannot resume with identical zone state or signal history. Long research
   runs must currently restart from the beginning.

3. **Historical dataset ingestion is not standardized.** The repository has
   mock bars but no canonical CSV/Parquet loader, schema
   version, or dataset identity. Reproducing a backtest currently depends on
   callers constructing the same `Bar` sequence.

4. **Session boundaries are fixed UTC windows.** London and New York daylight
   saving changes are not modeled, so session labels can be shifted by one hour
   during parts of the year.

5. **The strategy registry discovers Python modules through imports.** Import
   errors or module-level side effects can prevent catalog discovery. Strategy
   modules should therefore remain lightweight and deterministic.

## Testing gaps

1. No test currently exercises a future live-data provider.
2. No large multi-symbol dataset test measures runtime or memory behavior.
3. No regression fixture preserves expected results for a fixed historical
   dataset and configuration version.
4. Excel export depends on `openpyxl`; its workbook contents should be tested
   in environments where project dependencies are installed.
5. Boundary tests for every session opening/closing time and daylight-saving
   transition are incomplete.

## Missing abstractions

1. A versioned historical-data loader is needed before datasets can be shared
   and reproduced consistently.
2. Experiment metadata—dataset ID, configuration checksum, strategy version,
   and outcome-rule version—is not yet embedded in `BacktestResult`.
3. Multi-symbol strategies have no synchronized market-snapshot abstraction;
   bars are currently delivered one at a time in timestamp/symbol order.

## Scalability constraints

1. Backtests materialize and sort all bars in memory. This is simple and safe
   for current research but will constrain very large datasets.
2. Comparison runs are sequential and instantiate each strategy independently.
   Hundreds of experiments will repeat dataset traversal.
3. Signal outcomes are retained in every result, which can make JSON and Excel
   exports large for high-frequency experiments.
