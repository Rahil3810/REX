# Controlled Experiment: V1_WIDTH_FILTER vs Automatic Zone V1

**Experiment:** `width_filter_v1_experiment_v1`  
**Variant:** `V1_WIDTH_FILTER`  
**Pipeline:** `research_zones_smoke_v4` (baseline generation unchanged)  
**Window:** `2026-01-04` → `2026-07-03`  
**Timeframe:** M15  
**Evaluation:** Zone Evaluation V1 (`zone_eval_v1`) — unchanged  
**Unchanged:** `SwingClusterZoneGeneratorV1`, `AutomaticZoneGenerator`, live paths

## Research question

> Does the minimum zone-width / causal-ATR filter produce a stable and
> practically meaningful improvement over Zone V1, considering both outcome
> quality **and** coverage?

## Answer

**No for practical adoption.**

Classification: **`B_IMPROVES_BUT_DESTROYS_COVERAGE`**

The filter improves outcome distribution (lower broken, higher success) but
retains only ~20% of zones and ~37% of interactions — below substantial-coverage
thresholds. Broken-rate improvement is directionally consistent across
chronological thirds, but coverage loss is severe (especially in the final
third). **Preserve baseline Automatic Zone V1.** Do not adopt this filter.

## Predeclared threshold

| Parameter | Value | Rationale |
|-----------|------:|-----------|
| `min_width_atr_ratio` | **0.35** | Fixed **before** examining outcomes. Above diagnostic median width/ATR (~0.12) but **below** the diagnostic 0.5 bucket boundary (not outcome-tuned). Tests whether excluding the narrowest bands improves quality without adopting the diagnostic cut. |
| `atr_period` | 14 | Same causal ATR helper as Zone V1 (`causal_atr` at `origin_confirmation_index`). |

Eligibility rule (creation-time only):

```
(zone.high - zone.low) / causal_ATR(origin_confirmation_index) >= 0.35
```

Zones with missing or zero causal ATR are rejected.

## 1. Full window — baseline vs experiment

| Metric | Baseline V1 | V1_WIDTH_FILTER | Notes |
|--------|------------:|----------------:|-------|
| Total zones | 288 | 57 | 231 rejected |
| Total interactions | 7,186 | 2,679 | |
| Success rate | 0.299 | 0.330 | Δ +0.031 |
| Failure rate | 0.192 | 0.277 | Δ +0.085 |
| **Broken rate** | **0.508** | **0.393** | Δ **−0.116** |
| Unavailable rate | 0.002 | 0.002 | |
| Zone retention | — | **19.8%** | |
| Interaction retention | — | **37.3%** | |
| Median width/ATR | 0.116 | 0.663 | |
| Median MFE | 0.000390 | 0.000430 | |
| Median MAE | 0.000390 | 0.000420 | |

**Trade-off:** Broken rate drops materially, but at the cost of discarding ~80%
of zones and ~63% of interactions. Failure rate rises (fewer zones survive to
break structurally; survivors see more FAILURE outcomes relative to baseline mix).

## 2. Chronological thirds

| Third | Base zones | Exp zones | Rejected | Base ix | Exp ix | Base broken | Exp broken | Zone ret | Ix ret |
|-------|----------:|----------:|---------:|--------:|-------:|------------:|-----------:|---------:|-------:|
| first | 131 | 29 | 102 | 1,578 | 633 | 0.495 | 0.345 | 22.1% | 40.1% |
| middle | 99 | 30 | 69 | 1,490 | 763 | 0.467 | 0.371 | 30.3% | 51.2% |
| final | 217 | 21 | 196 | 2,343 | 515 | 0.518 | 0.358 | **9.7%** | **22.0%** |

Third broken-rate delta spread ≈ 0.064 (within stability threshold 0.08) —
outcome improvement is **directionally stable**, but coverage is **not**:
final third retains fewer than 10% of zones.

## 3. Classification logic

| Criterion | Result |
|-----------|--------|
| Broken improved (Δ ≥ 0.03) | Yes (−0.116) |
| Substantial zone retention (≥ 40%) | **No** (19.8%) |
| Substantial interaction retention (≥ 40%) | **No** (37.3%) |
| Stable across thirds (spread ≤ 0.08) | Yes |

→ **B**: improves outcomes but destroys too much coverage.

Lower broken rate alone is **not** “better.” The experiment fails the
coverage–quality trade-off required for practical adoption.

## 4. What was not changed

- Automatic Zone V1 generator (`core/zones/auto/`) — untouched
- Zone Evaluation V1 — unchanged semantics
- BreakoutStrategy, SignalEngine, execution, backtesting, production ingestion
- No additional filters, scoring, or threshold tuning based on outcomes

Implementation: `research/width_filter_experiment.py` (post-generation filter +
re-evaluation). CLI: `scripts/rex_width_filter_experiment.py`.

## 5. Tests

`tests/test_width_filter_experiment.py` — 8 tests covering:

- width/ATR eligibility and threshold boundary
- causal ATR at `origin_confirmation_index` (no future leakage)
- missing/zero ATR rejection
- baseline pipeline unchanged
- deterministic results and JSON serialization

Full suite: **494 tests passing** (486 baseline + 8 new).

## 6. Next diagnostic (if pursuing research)

Width/ATR at creation explains **direction** but a single minimum-width gate
at 0.35×ATR is too blunt — it removes most V1 output. Preserve baseline V1.

Candidates for **diagnostic** follow-up (not another V1 filter experiment):

1. **Zone formation geometry** — why median width/ATR ≈ 0.12? Is half-width
   from single-swing ATR scaling the root cause?
2. **Volatility-regime interaction** — does narrow-band broken rate vary by ATR
   percentile at creation (without adopting a filter)?
3. **Interaction-path diagnostics** — wick-only vs close-through (already noted
   in geometry study; definitional with eval, not a generation lever).

Do **not** threshold-sweep width/ATR or stack filters on V1 without a new
predeclared hypothesis.

## Disclaimer

All rates are Zone Evaluation V1 **outcomes** on historical data, not
predictive accuracy or trading performance.
