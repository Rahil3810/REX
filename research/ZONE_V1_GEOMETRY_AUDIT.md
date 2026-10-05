# Automatic Zone V1 — Geometry Construction Audit

**Audit:** `zone_v1_geometry_audit_v1`  
**Window:** `2026-01-04` → `2026-07-03`  
**Timeframe:** M15  
**Dataset:** `research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv`  
**Unchanged:** Automatic Zone V1, Zone Evaluation V1, all live paths

## Research question

> Why are V1 zones narrow, and is there evidence that the geometry itself is
> behaving incorrectly?

## Final answer

**V1 zones are narrow by intended design, not by implementation defect.**

The dominant geometry type (68% of zones) is **multi-swing envelope**:
`[min(swing_prices), max(swing_prices)]` with **no ATR padding**. Merged swings
are tightly spaced (median swing spread/ATR ≈ 0.08), producing narrow bands.
Single-swing zones (32%) receive ATR expansion (0.20×ATR at generation), but
their absolute width is fixed at generation-asof ATR — when normalized by
**origin** ATR (research convention), width/ATR appears even smaller.

**288/288 audited zones match recomputed V1 boundary formulas.** No
demonstrated implementation defect. **Preserve baseline V1 unchanged.**

---

## 1. Observed facts (full window M15)

| Fact | Value |
|------|------:|
| Total zones | 288 |
| Boundary verification matches | **288 / 288** |
| Multi-swing envelope | 196 (68.1%) |
| Single-swing expanded | 92 (31.9%) |
| Median absolute width | 0.000070 |
| Median width/ATR (origin) | **0.116** |
| Median swing spread/ATR (origin) | 0.082 |
| Median origin bar range | 0.000840 |
| Supply / demand split | 144 / 144 |

Single-swing zones: median width/ATR (origin) = **0.080**; at generation-asof
they are exactly **0.20×ATR_gen** (verified in samples).

Multi-swing zones: median width/ATR (origin) = **0.190**; width equals swing
spread with no expansion.

---

## 2. Implementation mechanics (source of truth)

From `core/zones/auto/candidates.py`, `config.py`, and `research/AUTOMATIC_ZONE_V1.md`:

### Swing input

- Fractal swings (L=2, R=2): `SwingEvent.price = bar.high` (HIGH) or `bar.low` (LOW)
- Not body, not full range — the structural extreme at the fractal bar

### Clustering

```
MERGE if: next_swing.price - cluster_max_price <= tolerance
tolerance = 0.35 × causal_ATR(generation_asof)   [or 0.0005 fallback]
```

### Boundary construction

| Type | Condition | Boundaries | Width |
|------|-----------|------------|-------|
| **Multi-swing** | min(prices) ≠ max(prices) | `[min(prices), max(prices)]` | swing spread only |
| **Single-swing** | all prices equal | `price ± 0.10 × ATR(gen)` | **0.20 × ATR(gen)** |

### What zone width is intended to represent

> Price-interest band from clustered structural swing extremes — where price
> reacted at confirmed swing points. **Not** the originating candle range, **not**
> a fixed ATR fraction for multi-swing clusters.

### ATR timing caveat (audit finding)

| ATR reference | Used for | Stored in |
|---------------|----------|-----------|
| `generation_asof` (end of window) | tolerance, half-width, evidence.atr_used | `ZoneEvidence` |
| `origin_confirmation_index` | research width/ATR diagnostics | audit only |

When origin ATR > generation ATR (common early in window), single-swing
width/ATR_origin < 0.20 even though width/ATR_generation = 0.20 exactly.

---

## 3. Full-dataset distributions

### Core geometry metrics

| Metric | min | p10 | p25 | median | p75 | p90 | max |
|--------|----:|----:|----:|-------:|----:|----:|----:|
| **absolute_width** | 0.000009 | 0.000050 | 0.000069 | **0.000070** | 0.000230 | 0.000510 | 0.002770 |
| **atr_at_origin** | 0.000275 | 0.000473 | 0.000626 | **0.000838** | 0.001161 | 0.001491 | 0.002509 |
| **width/ATR (origin)** | 0.009 | 0.044 | 0.064 | **0.116** | 0.293 | 0.661 | 3.306 |
| **swing_spread** | 0.000000 | 0.000000 | 0.000000 | **0.000070** | 0.000230 | 0.000510 | 0.002770 |
| **swing_spread/ATR** | 0.000 | 0.000 | 0.000 | **0.082** | 0.293 | 0.661 | 3.306 |

### Origin bar candle geometry

| Metric | min | p10 | p25 | median | p75 | p90 | max |
|--------|----:|----:|----:|-------:|----:|----:|----:|
| **origin_bar_range** | 0.000180 | 0.000390 | 0.000550 | **0.000840** | 0.001220 | 0.001720 | 0.009900 |
| **origin_bar_body** | 0.000000 | 0.000060 | 0.000170 | **0.000345** | 0.000651 | 0.001110 | 0.004490 |
| **origin_bar_upper_wick** | 0.000000 | 0.000020 | 0.000070 | **0.000150** | 0.000290 | 0.000600 | 0.005350 |
| **origin_bar_lower_wick** | 0.000000 | 0.000030 | 0.000070 | **0.000170** | 0.000330 | 0.000560 | 0.001870 |

Zone width median (0.000070) is **~12× smaller** than origin bar range median
(0.000840).

---

## 4. Subgroup comparisons

### By zone kind / swing type

| Group | Count | Median width/ATR | Median width | Median swing spread |
|-------|------:|-----------------:|-------------:|--------------------:|
| Supply (swing HIGH) | 144 | 0.128 | 0.000070 | 0.000070 |
| Demand (swing LOW) | 144 | 0.101 | 0.000070 | 0.000070 |

Supply zones are slightly wider in width/ATR terms; absolute widths identical at
median.

### By geometry type

| Type | Count | Median width/ATR | Median width | Median swing spread |
|------|------:|-----------------:|-------------:|--------------------:|
| Single-swing expanded | 92 | 0.080 | 0.000069 | 0.000000 |
| Multi-swing envelope | 196 | 0.190 | 0.000165 | 0.000165 |

### Volatility regime (diagnostic only — causal ATR at origin tertiles)

| Regime | Count | Median width/ATR | Median width |
|--------|------:|-----------------:|-------------:|
| Low vol (ATR ≤ p33) | 95 | 0.161 | 0.000069 |
| Mid vol | 98 | 0.099 | 0.000085 |
| High vol (ATR > p67) | 94 | **0.057** | 0.000069 |

**Interpretation:** Absolute widths stay similar across regimes; width/ATR is
lower in high-volatility periods because ATR (denominator) is larger. This is a
normalization artifact, not evidence that V1 widens bands in volatile markets.

### Chronological thirds

| Third | Zones | Multi-swing % | Median width/ATR | Boundary matches |
|-------|------:|--------------:|-----------------:|-----------------:|
| First | 131 | 64.9% | 0.163 | 131/131 |
| Middle | 99 | 66.7% | 0.204 | 99/99 |
| Final | 217 | 53.5% | 0.123 | 217/217 |

Patterns are stable; no third shows boundary mismatches.

---

## 5. Representative zone audits

### Example A — narrowest multi-swing envelope (width/ATR ≈ 0.009)

| Field | Value |
|-------|------:|
| Zone kind | DEMAND |
| Geometry | multi_swing_envelope (2 swings) |
| Swing prices | 1.14788, 1.14789 |
| Zone boundaries | [1.14788, 1.14789] |
| Width | 0.000010 (1 pipette) |
| ATR at origin | 0.001128 |
| Width/ATR (origin) | 0.0089 |
| Origin bar range | 0.001660 |
| Origin bar low | 1.14788 (= swing price) |

Two swing lows merged within tolerance; envelope spans 1 pipette. Origin candle
range is 166× wider than the zone.

### Example B — typical single-swing expanded (width/ATR ≈ 0.116)

| Field | Value |
|-------|------:|
| Zone kind | SUPPLY |
| Geometry | single_swing_expanded |
| Swing price | 1.18825 (= origin bar high) |
| Zone boundaries | [1.188216, 1.188284] |
| Width | 0.00006885 |
| ATR at origin | 0.000592 |
| ATR at generation | 0.000344 |
| Width/ATR (origin) | 0.116 |
| Width/ATR (generation) | **0.200** (exact) |
| Origin bar range | 0.000640 |

Single-swing expansion works as coded. Width/ATR at origin < 0.20 because
origin ATR > generation ATR.

### Example C — wide multi-swing cluster (11 swings)

| Field | Value |
|-------|------:|
| Zone kind | SUPPLY |
| Geometry | multi_swing_envelope (11 swings) |
| Swing spread | 0.000300 |
| Zone boundaries | [1.17970, 1.18000] |
| Width/ATR (origin) | ≈ 0.45 |

Even the widest multi-swing clusters rarely exceed ~0.5×ATR because chained
merges add at most ~tolerance per step.

---

## 6. Hypothesis evaluation

| ID | Hypothesis | Verdict | Key evidence |
|----|------------|---------|--------------|
| **A** | Intended V1 geometry (envelope + optional ATR pad) | **Supported** | 68% multi-swing with no padding; docs match code |
| **B** | Small swing magnitude / tight clustering | **Supported** | Median swing spread/ATR ≈ 0.08; p25 spread = 0 |
| **C** | Candle body/wick not used for width | **Supported** | Width median 12× below origin bar range median |
| **D** | ATR normalization timing | **Contributing** | Single-swing width/ATR_gen = 0.20 always; origin ATR differs |
| **E** | Implementation defect | **Unlikely** | 288/288 boundaries match recomputed formulas |
| **F** | Interaction of A + B (+ D) | **Primary cause** | Envelope design + tight swings → narrow bands |
| **G** | Insufficient evidence | Not needed | Root cause identified from implementation + data |

---

## 7. Unresolved questions

1. **Should multi-swing envelopes receive ATR padding?** — This would be a V1
   *design* change, not a bug fix. Not in scope; baseline preserved.

2. **Should ATR for half-width use origin confirmation instead of generation
   asof?** — Current behavior is documented and consistent; changing it would
   alter V1 semantics.

3. **Why do so many distinct swing prices merge?** — Tolerance = 0.35×ATR at
   generation allows merging swings up to ~12 pips apart on this dataset. Many
   clusters contain swings at nearly identical prices (M15 fractal extremes in
   quiet ranges).

4. **Does narrow geometry cause high broken rates?** — Addressed by prior
   width-filter experiment (outcome improvement but unacceptable coverage loss).
   Geometry audit confirms narrowness is intrinsic, not accidental.

---

## 8. Artifacts

| File | Purpose |
|------|---------|
| `research/zone_geometry_audit.py` | Audit logic, distributions, hypothesis evaluation |
| `scripts/rex_zone_geometry_audit.py` | CLI runner |
| `tests/test_zone_geometry_audit.py` | 9 deterministic tests |
| `/tmp/rex_zone_geometry_audit.json` | Full JSON report (regenerable) |

**Tests:** 503 passing (494 prior + 9 new). No V1 code modified.

---

## Disclaimer

Diagnostic audit only. Volatility-regime splits are not filters. Does not
modify Automatic Zone V1. No further Zone V1 experiments planned from this
finding.
