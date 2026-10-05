# Automatic Zone V1 — Extended Real-Data Stability Evaluation

**Pipeline:** `research_zones_smoke_v2`  
**Dataset:** `research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv`  
**Window:** discovered bounds `2026-01-04` → `2026-07-03` (not hard-coded)  
**Report:** `/tmp/rex_research_zones_smoke.json`  
**Classification:** `V1_STABLE_ENOUGH_FOR_NEXT_EXPERIMENT`

This note summarizes a research-only evaluation. Rates are **zone_eval_v1
outcomes**, not predictive accuracy or “zone accuracy.”

## What the larger sample shows

Over ~6 months of free EURUSD M1 (176,840 accepted bars; 9,389 invalid OHLC
dropped; `tick_volume` preserved, unused by generation):

| TF | Resampled bars | Incomplete buckets | Swings | Zones | Interactions | Success* | Broken* |
|----|----------------|--------------------|--------|-------|--------------|----------|---------|
| M15 | 6,679 | 5,731 | 1,789 | 288 | 7,186 | ~0.30 | ~0.51 |
| H1 | 464 | 2,639 | 127 | 72 | 356 | ~0.35 | ~0.56 |
| H4 | 9 | 797 | 2 | 2 | 0 | n/a | n/a |
| D1 | 2 | 154 | 0 | 0 | 0 | n/a | n/a |

\*Decisive outcomes only (SUCCESS + FAILURE + BROKEN).

M15 and H1 both produce enough zones and interactions for a stability judgment.
Broken remains the modal decisive outcome (~50–56%), with success ~30–35%.
That pattern is **consistent**, not an artifact of a 3-day smoke window.

## Is the broken/success distribution stable?

Independent chronological thirds of the same window:

| Segment | Dates | M15 zones | M15 success | M15 broken | H1 success | H1 broken |
|---------|-------|-----------|-------------|------------|------------|-----------|
| first | 2026-01-04 … 03-04 | 131 | 0.314 | 0.495 | 0.395 | 0.442 |
| middle | 2026-03-05 … 05-04 | 99 | 0.305 | 0.467 | 0.369 | 0.536 |
| final | 2026-05-05 … 07-03 | 217 | 0.306 | 0.518 | 0.380 | 0.507 |

- M15 success_rate spread ≈ **0.008**
- M15 broken_rate spread ≈ **0.051**
- H1 success_rate spread ≈ **0.026**
- H1 broken_rate spread ≈ **0.094**

Zone *counts* vary by segment (especially M15 final third), but **outcome
mixes stay within the stability threshold** (±0.20). V1 behavior is not
dominated by one small period.

## Do M15 / H1 have enough interactions?

Yes.

- M15: 288 zones, 7,186 interactions (~25 per zone); 270 zones with multiple
  interactions; only 12 with zero.
- H1: 72 zones, 356 interactions (~5 per zone); enough for rate estimates.

Median zone widths remain tight (M15 ~0.7e-4; H1 ~2.4e-4). Median strength is
low (M15 ~2, H1 ~1). Combined with the high broken share, this supports a
diagnostic hypothesis of **over-tight / fragile bands**, not sample noise.

## Are H4 / D1 usable?

**Not yet** under strict `fx_open_minutes_v1` completeness on this free sample.

- H4: only 9 complete bars → 2 zones, **0** interactions.
- D1: only 2 complete bars → no swings/zones.

Do not use H4/D1 rates from this dataset to judge V1. A denser M1 source or a
longer continuous series (or a carefully justified completeness relaxation for
research-only HTF) is required before HTF>H1 conclusions.

## Volume

`volume_type=tick_volume`. Bars carry volume for reporting only. Automatic Zone
V1 does **not** use volume in this experiment.

## Classification rationale

`V1_STABLE_ENOUGH_FOR_NEXT_EXPERIMENT` because:

1. M15 has far more than the minimum zones/interactions.
2. Outcome rates are stable across thirds.
3. H1 corroborates the same broken-dominant pattern.

This does **not** mean V1 is good enough to trade. It means the diagnosis is
stable enough to justify a **controlled** next experiment (still research-only),
without changing the algorithm in this step.

## What to investigate next (do not auto-optimize yet)

1. **Why broken ≈ 50%+** — bound width vs ATR, single-swing expansion, lifecycle
   break definition vs evaluation break definition.
2. **Touches vs breaks** — many zones receive multiple interactions yet still
   break; separate “first touch” outcomes from later mitigation.
3. **Strength / cluster size** — does multi-swing clustering improve outcomes vs
   single-swing zones?
4. **H1 confirmation** — repeat diagnostics on H1 with the same hypotheses.
5. **H4/D1** — only after denser complete buckets exist; do not relax
   completeness silently.
6. Keep evaluation methodology (`zone_eval_v1`) fixed while changing at most one
   generation knob at a time.

## How to reproduce

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_research_zones_smoke.py \
  --symbol EURUSD \
  --timeframes M15 H1 H4 D1
```

Optional `--start` / `--end` override the discovered dataset bounds.
