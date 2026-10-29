# MA Confluence Zone V1 (Research Spec)

**Method id:** `ma_confluence_zone_v1`  
**Generator version:** `ma_confluence_zone_v1.0.0`  
**First validation experiment:** EURUSD **H1**

## Research questions (keep separate)

| ID | Question | How answered |
|----|----------|--------------|
| **A** | Are automatically generated MA zones visually/structurally meaningful? | Manual VALID / WEAK / INVALID labels |
| **B** | Do S002 breakout→retest setups around those zones have measurable edge? | Deferred historical S002 evaluation |

A high VALID rate does **not** prove S002 profitability.

## Frozen V1 configuration

Do not retune these parameters against the first labeled sample.

| Parameter | Value |
|-----------|------:|
| EMA fast / slow / trend | 20 / 50 / 200 |
| ATR | 14 |
| `k_enter` | 0.30 |
| `k_exit` | 0.60 |
| `min_persist` | 3 |
| `exit_persist` | 3 |
| `min_width_atr` | 0.25 |

**EMA200 is evidence-only** — not used as a confluence gate.

## Causality

At candle `t`, only `bars[0:t+1]` and IndicatorEngine EMA/ATR on that prefix.

## Creation / freeze / expire

1. Convergence: `abs(EMA20 - EMA50) / ATR14 <= k_enter` for `min_persist` bars.
2. Create frozen zone: ATR-padded `min/max(EMA20, EMA50)` with width floor `min_width_atr * ATR`.
3. Bounds do not move while active.
4. Expire after `exit_persist` bars with `sep/ATR > k_exit`.
5. Retain all historical snapshots. New confluence after expire → new `zone_id`.
6. At most one *current* active cluster; retention is unlimited.

## ATR source

`IndicatorEngine.atr` (pandas-ta). Not the same as swing-zone `causal_atr`.

## Export / CLI

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_ma_confluence_candidates.py \
  --symbol EURUSD --timeframe H1
```

Outputs JSON + CSV with manual-review columns including `convergence_start`,
`convergence_duration`, `distance_from_price`, and `chart_hint`.

### Observed first-window sample (do not retune)

On free-OHLC EURUSD `2026-01-04` → `2026-07-03`, H1 produced **7** candidates
with the frozen V1 config (all expired by window end). That is below the
aspirational 100+ validation size. Expanding sample size must use **more
history / symbols / timeframes as separate frozen batches** — not parameter
tuning on this set.

## Phases

1–3 implemented (types, generator, export).  
4–7 (label schema analysis, S002 integration) only after reviewing Q-A evidence.
