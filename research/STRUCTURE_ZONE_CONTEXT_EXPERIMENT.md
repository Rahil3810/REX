# Structure-Context Diagnostic on Automatic Zone V1 Outcomes

**Experiment:** `structure_zone_context_v1`  
**Pipeline:** `research_zones_smoke_v3`  
**Window:** `2026-01-04` → `2026-07-03` (discovered bounds)  
**APIs reused:** `FeatureRepository.materialize(..., asof=origin_confirmation_time)` +  
`TrendView.project(..., market_structure_v1)`  
**Zone / eval algorithms:** unchanged

## Research question

> Does market-structure context appear to explain the high broken-zone rate
> enough to justify a subsequent controlled Zone V1 experiment?

## Answer

**No.**

Conclusion code: `STRUCTURE_DOES_NOT_EXPLAIN_ENOUGH`

Aligned vs opposed M15 zones have nearly identical broken and success rates
(broken ≈ 0.50–0.51; success ≈ 0.29–0.30). Sample sizes are large enough to
interpret. Structure context does **not** explain the high broken rate enough
to justify changing Automatic Zone V1 yet.

Rates remain zone_eval_v1 **outcomes**, not predictive accuracy.

## Method (causal)

For each M15 Automatic Zone V1 zone:

1. Take `origin_confirmation_time` / `origin_confirmation_index` as creation time T.
2. Materialize `PACK_STRUCTURE` with `asof=T` (entry-TF only; no HTF mapping).
3. Project `market_structure_v1` → `MarketTrend`.
4. Buckets:
   - structure: `bullish` / `bearish` / `neutral_unclear` (ranging + unknown)
   - alignment: DEMAND↔bullish and SUPPLY↔bearish → `aligned`; reverse → `opposed`;
     else `neutral_unclear`
5. Stratify existing Zone Evaluation V1 outcomes (no eval semantics changed).

## Full-window M15 results

| Bucket | Zones | Interactions | Success | Failure | Broken | Too small? |
|--------|------:|-------------:|--------:|--------:|-------:|:-----------|
| structure/bullish | 74 | 1,576 | 0.294 | ~0.17 | **0.534** | No |
| structure/bearish | 113 | 2,832 | 0.302 | ~0.21 | **0.486** | No |
| structure/neutral_unclear | 101 | 2,778 | 0.300 | ~0.18 | **0.516** | No |
| alignment/aligned | 98 | 2,314 | 0.304 | ~0.19 | **0.506** | No |
| alignment/opposed | 89 | 2,094 | 0.294 | ~0.21 | **0.500** | No |
| alignment/neutral_unclear | 101 | 2,778 | 0.300 | ~0.18 | **0.516** | No |

Aligned−opposed broken gap ≈ **0.006** (threshold used: 0.10).  
All primary buckets are **large enough to interpret**.

## Chronological thirds (stability check, not validation)

Alignment broken rates stay high and similar across thirds; spreads are small
relative to the diagnostic threshold. Thirds confirm the full-window finding is
not a single-period artifact.

## What this does *not* say

- Does not prove structure is useless for other research questions.
- Does not recommend ignoring structure forever.
- Does not authorize Zone V1 algorithm changes based on this experiment.

## What to investigate instead (still without changing V1 yet)

The broken-dominant pattern looks **structure-agnostic** on this sample. Next
diagnostics should focus on zone geometry / lifecycle itself (width vs ATR,
single-swing expansion, break definition vs evaluation break), not a
structure-gated generation rule.

## Reproduce

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_research_zones_smoke.py \
  --symbol EURUSD \
  --timeframes M15 H1
```
