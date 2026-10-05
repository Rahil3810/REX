# Geometry / Lifecycle Diagnostic on Automatic Zone V1 Outcomes

**Experiment:** `geometry_lifecycle_zone_v1`  
**Pipeline:** `research_zones_smoke_v4`  
**Window:** `2026-01-04` → `2026-07-03`  
**Reuse:** `causal_atr` (same helper as Zone V1/eval), `SwingGenerator`, zone_eval_v1 interactions  
**Unchanged:** Automatic Zone V1, Zone Evaluation V1 semantics

## Research question

> Is the high broken-zone rate plausibly associated with a measurable zone
> geometry or lifecycle characteristic that is strong and stable enough to
> justify ONE controlled Zone V1 experiment?

## Answer

**Yes — with caveats — on zone width / ATR.**

Conclusion code: `GEOMETRY_LIFECYCLE_APPEARS_MATERIAL`

Narrow zones (`width/ATR < 0.5`) show materially higher broken rates than
moderately wider zones (`0.5–1`), with adequate full-window samples. Age-to-first
interaction and supply vs demand do **not** explain the broken rate. This may
justify **ONE** controlled Zone V1 experiment focused on minimum band width
relative to causal ATR (e.g. floor on single-swing half-width) — not threshold
fishing, not a structure gate, and not a change to Zone Evaluation V1.

Rates remain zone_eval_v1 **outcomes**, not predictive accuracy.

## 1. Baseline (full window M15)

| Metric | Value |
|--------|------:|
| Zones | 288 |
| Interactions | 7,186 |
| Success | 0.299 |
| Failure | 0.192 |
| Broken | **0.508** |
| Unavailable | ~0.002 |

Median `width/ATR` ≈ **0.12** (most zones are very narrow vs ATR).

## 2. Geometry diagnostics (creation-time ATR)

| width/ATR bucket | Zones | Ix | Broken | Success | Too small? |
|------------------|------:|---:|-------:|--------:|:-----------|
| **lt_0.5** | 247 | 4,968 | **0.568** | 0.284 | No |
| **0.5_to_1** | 27 | 1,420 | **0.429** | 0.327 | No |
| 1_to_2 | 10 | 518 | 0.303 | 0.371 | **Yes** |
| gt_2 | 3 | 221 | 0.258 | 0.276 | **Yes** |
| atr_unavailable | 1 | 59 | — | — | **Yes** |

- Interpretable gap (lt_0.5 vs 0.5_to_1): broken Δ ≈ **0.14** (threshold 0.10).
- Wider buckets trend even lower broken but are **too small to interpret**.
- Supply vs demand: broken ≈ 0.504 vs 0.512 — **not material**.

## 3. Lifecycle diagnostics

| Age to first interaction | Zones | Ix | Broken | Too small? |
|--------------------------|------:|---:|-------:|:-----------|
| lt_1h | 112 | 3,254 | 0.480 | No |
| 1–4h | 77 | 1,891 | 0.533 | No |
| 4–24h | 57 | 1,149 | 0.536 | No |
| gt_24h | 30 | 892 | 0.523 | No |
| no_interaction | 12 | 0 | — | Yes |

Age gap ≈ 0.06 — **below** material threshold. Prior-touch buckets at interaction
time also show no large, clean gradient.

## 4. Interaction / break diagnostics (not generation levers)

| Style | Ix | Broken | Success | Note |
|-------|---:|-------:|--------:|------|
| close_through | 2,606 | 0.781 | 0.199 | Largely aligned with eval break definition |
| wick_only | 2,514 | 0.301 | 0.338 | |
| close_inside | 1,793 | 0.460 | 0.353 | |

Close-through vs wick is informative about **how** breaks present, but it is
**not** a clean creation-time geometry lever (and partly definitional with
`zone_eval_v1` broken = close beyond structural side). Do **not** treat this as
the Zone V1 experiment candidate.

## 5. Chronological-third stability

- `lt_0.5` remains the dominant cohort every third; broken stays high
  (~0.55–0.59) — stable.
- `0.5_to_1` shows lower broken in every third (~0.34–0.40) but is
  **too small within each third alone** (zones 9–14).
- Therefore: direction is consistent; within-third confirmation of the
  contrast bucket is sample-limited. Full-window contrast remains the primary
  evidence.

## 6. Interpretation

| Dimension | Material? | Stable enough? |
|-----------|:---------:|:---------------|
| width / ATR (narrow vs moderate) | **Yes** | Directionally yes; contrast bucket thin in thirds |
| age to first touch | No | — |
| supply vs demand | No | — |
| close-through vs wick | Strong but definitional | Not a V1 generation experiment |

**Recommended next step (still do not implement here):**  
ONE controlled research experiment on Automatic Zone V1 **minimum width /
ATR expansion** (creation-time only), keeping Zone Evaluation V1 fixed, and
re-measuring broken/success on the same EURUSD window + thirds.

**Not recommended yet:** structure gates, age filters, eval-semantic changes,
or optimizing bucket edges.

## Reproduce

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_research_zones_smoke.py \
  --symbol EURUSD \
  --timeframes M15 H1 \
  --no-structure-context
```
