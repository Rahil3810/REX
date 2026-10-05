# REX MARKET ENGINE VERIFICATION REPORT

**Date:** 2026-08-29  
**Mode:** Read-only verification + independent golden-vector tests  
**Production code modified:** No  
**Verification suite:** `tests/test_market_engine_verification.py` (58 tests, all PASS)

This report verifies whether existing implementations produce correct results for their stated purpose. It does not redesign architecture.

---

## Verification Suite Summary

| Result | Count |
|--------|------:|
| PASS (tests executed) | 58 |
| Production files changed | 0 |

Tests assert independently calculated expectations (exact swing prices, return sums, RVOL ratios, MTF scores, pip distances, session boundaries), not merely “value is not None”.

---

## 1. Swing Detection

1. **Location:** `core/features/generators/swings.py` — `SwingGenerator`, `_find_swings`
2. **Functions tested:** `_find_swings`, `generate`
3. **Claims:** Strict local extrema with configurable left/right confirmation
4. **Actually does:** For each index in `[left, len-right)`, appends high if strictly greater than all highs in left+right windows; same for lows with strict less-than. Returns price tuples only.
5. **Tests:** Golden vector (exact prices 15,14 / 7,6); equal highs; right-boundary unconfirmed; left-boundary excluded; config L/R; insufficient bars; chronological order
6. **Expected:** Exact swing prices `(15.0, 14.0)` / `(7.0, 6.0)` for hand-built OHLC
7. **Actual:** Matches
8. **Verdict:** **PASS** — **GREEN**
9. **Research risk:** Low for price-only extrema; high for event referencing (no index/time)
10. **Next:** Enrich swing model with index/timestamp (do not change detection math)

---

## 2. Swing Model

1. **Location:** `TimeframeSwings`, `SwingFeatures`, `StructurePack`
2. **Fields retained:** `timeframe`, `swing_highs: tuple[float,...]`, `swing_lows: tuple[float,...]`
3. **Claims:** Structure features for trend views
4. **Actually retains:** Prices only, chronological detection order
5. **Unavailable (verified):** swing bar index, timestamp, high/low kind as events, swing ID, ability for BOS to reference the exact swing bar
6. **Verdict:** **PARTIAL** — **YELLOW**
7. **Risk:** Downstream cannot answer “when/where” a swing occurred
8. **Next:** ADD index + timestamp to swing representation

---

## 3. HH / HL / LH / LL

1. **Search result:** No typed HH/HL/LH/LL models. Appear only in `TrendView._classify_swings` reason strings (“higher highs”, “higher lows”, …).
2. **Classification:** **C — represented only in strings/reasons** (internally inferred via consecutive comparisons)
3. **Tests:** Bullish rising highs+lows → reason contains “higher highs”; mixed rising highs + falling lows → `RANGING` (not partial HH/HL object)
4. **Verdict:** **PARTIAL** — **YELLOW** (inference works for trend enum; not explicit structure events)
5. **Risk:** AI/consumer may treat “higher highs” prose as structured evidence
6. **Next:** ADD explicit structure-event types if SMC language is required; else document as prose-only

---

## 4. BOS

1. **Location:** `strategies/rules/bos_rule.py` — `BOSRule.detect`  
   Feature/MarketState: **absent**
2. **Actual definition:** Close beyond lookback window max-high / min-low among `candles[-lookback-1:-1]`. Requires caller `bullish`/`bearish` flags. Wick-only does not qualify. Strength = `min(100, int((breakout+body)*10000))`.
3. **Tests:** Close break detects; wick-only fails; broken level can be **non-fractal** lookback max (16.0 vs fractal swings 15/14); flags required
4. **Verdict:** **PASS for lookback breakout rule** — **ORANGE** as “market structure BOS”
5. **Risk:** Misleading name — not fractal-swing BOS; unused by strategies; disconnected from `SwingGenerator`
6. **Next:** FIX naming/docs or REPLACE with swing-referenced BOS; do not feed to AI as structural BOS today

---

## 5. CHOCH

1. **Search:** No `choch*.py` in working tree; `StructurePack` has only `swings`
2. **Verdict:** **NOT IMPLEMENTED** — **RED**
3. **Next:** DEFER until swing model has timestamps/IDs

---

## 6. Trend

1. **Location:** `core/features/views/trend.py` — `TrendView`, `_classify_swings`, `_market_structure_v1`, `_trend_strength`
2. **Claims:** `market_structure_v1` trend from swings + strength + MTF
3. **Actually does:**
   - Trend from last N swing highs/lows rising/falling (N=`minimum_swings`)
   - **Strength = config lookup** (`aligned_structure_score=85`, `ranging=35`, `unknown=0`) — **not** calculated confidence or normalized magnitude
4. **Tests:** Strength always 85 for any bullish; unknown → 0
5. **Verdict:** **PASS for stated algorithm** — **YELLOW** (strength is a constant table, not confidence)
6. **Risk:** MarketState field `strength: 85` looks like confidence; it is not
7. **Next:** FIX naming (`structure_score` / document as config enum score) before AI use

---

## 7. Multi-Timeframe

1. **Location:** `_multi_timeframe_agreement`; mapping in `FeatureConfig` / `config/market_structure.json`
2. **Claims:** Higher TF confirmation scores
3. **Actually does:**
   - A. Configured: M15→(M30,H1,H4), etc.
   - B/C/D. **Caller supplies** HTF bars; REX does **not** resample
   - E. No timestamp alignment logic
   - F. Future HTF info possible if caller builds bad HTF candles
   - G. Score: aligned=85 / partial=55 / neutral=35 / unknown=0 (config)
4. **Tests:** Conflicting TFs → partial (not “all agree”); all disagree → neutral; missing HTF → partial + “Missing”; only M15 materialized → no H1/H4 in pack
5. **Verdict:** **PASS for equality scoring** — **ORANGE** for research MTF (no causal HTF construction)
6. **Risk:** “All configured higher timeframes agree” can be true on identical synthetic data while real HTF is misaligned
7. **Next:** ADD causal HTF resampling (P0); keep score function

---

## 8. Momentum

1. **Location:** `MomentumView` / `ts_mom_v1`; `ReturnsGenerator`; `MomentumRule` placeholder
2. **Actual algorithm:** `sum(simple_returns[-min(20,n):])`; direction = sign; strength = abs(sum). Lookback **hardcoded 20** (not in FeatureConfig).
3. **Tests:** Independent cumulative return match; lookback=20 vs all-returns differ; empty → UNKNOWN; zero previous close → return 0.0
4. **Verdict:** **PASS for stated simple TSMOM** — **YELLOW** (hardcoded lookback; zero coercion)
5. **Next:** FIX make lookback configurable; FIX invalid price → explicit unavailable instead of 0.0

---

## 9. Indicators (RSI / MACD / EMA / ATR / RVOL)

1. **Location:** `PandasTAProvider`, `IndicatorEngine`, pack last-scalar extraction
2. **Results:**
   - SMA exact `(1,2,3)→2`, etc. — **PASS GREEN**
   - RSI monotonic up ≥70 after warmup — **PASS GREEN** (library)
   - MACD hist ≈ macd−signal — **PASS GREEN**
   - ATR positive after warmup — **PASS GREEN**
   - RVOL exact 2.5; excludes current; NaN on insufficient/missing — **PASS GREEN**
3. **Verdict:** **GREEN** for research scalars (with library trust boundary)
4. **Risk:** RSI/MACD depend on pandas-ta-classic; warm-up NaNs correctly become pack `None`
5. **Next:** KEEP; pin library version in requirements if not already strict

---

## 10. Volatility / Range Expansion

1. **Location:** `RangeExpansionGenerator`, `VolatilityView`
2. **Formula:** `ratio = mean(|c-o| recent) / mean(|c-o| historical)`; thresholds low/high
3. **Overlap:** **Confirmed** — `recent = bars[-recent_window:]` is a **subset** of `historical = bars[-historical_window:]`. Implementation artifact of nested windows (not exclusive prior window).
4. **Insufficient history:** returns `NORMAL` with `ratio=None` (soft default)
5. **Zero hist avg:** `LOW`, `ratio=None`
6. **Tests:** Known bodies → ratio 2.5/1.6; soft NORMAL; zero body LOW
7. **Verdict:** **PASS for coded formula** — **ORANGE** (overlap + soft NORMAL)
8. **Next:** FIX insufficient → unavailable; consider exclusive prior baseline (REPLACE if research requires)

---

## 11. Phase

1. **Location:** `PhaseView` / `heuristic_v1`
2. **Order:** compression → range/unknown → pullback → strong trend → **else REVERSAL**
3. **REVERSAL:** Residual fallback (“Directional structure without strong-trend strength”) — **no positive reversal evidence**
4. **Verdict:** **PASS as heuristic** — **ORANGE**
5. **Next:** FIX rename residual or require positive reversal evidence; do not treat as true reversal for AI

---

## 12. Zones

1. **Location:** `ZoneEngine`, `ManualZoneProvider`, `ChartAnalyzer`, JSON config
2. **Nature:** **B — manually supplied** (engine does not detect)
3. **Verified:** strongest-inside (ZoneEngine id=2); first-inside (ChartAnalyzer id=1); **dual-path disagreement**; nearest edge distance 300/200 pips independently calculated
4. **Verdict:** **PASS for query engine** — **YELLOW** (manual + dual semantics)
5. **Next:** FIX unify active-zone selection; document manual provenance in MarketState

---

## 13. Session

1. **Location:** `SessionManager`; `AlwaysOpenCalendar` stub (`is_trading` always True)
2. **Verified:** London/NY overlap + high liquidity at 14:00 UTC; start inclusive / end exclusive; research overlap bucket; calendar stub; **naive datetime silently accepted** (local TZ via `astimezone`)
3. **DST/holidays:** Not modeled (mega-session windows only)
4. **Verdict:** **PASS for mega-session labels** — **YELLOW**
5. **Next:** FIX reject naive timestamps; DEFER holiday calendar

---

## 14. MarketState

1. **Location:** `core/market_state/{models,builder}.py`
2. **Fidelity:** Indicator scalars match IndicatorPack; liquidity always `unsupported`; strength 85 preserved as config constant
3. **Lost vs FeatureContext:** full return series, full swing lists beyond entry snapshot (entry swings kept), raw bars, pack schema details
4. **Overclaim risk:** `structure.strength`, phase `reversal`, MTF “agree” prose, zones without “manual” flag
5. **Verdict:** **PASS as packaging layer** — **YELLOW**
6. **Next:** FIX field naming/docs; do not connect AI until P0 items addressed

---

## 15. Data Quality

| Case | Behavior | Risk |
|------|----------|------|
| Duplicate timestamps | Parser rejects | Good |
| Invalid OHLC | Parser rejects | Good |
| Missing coverage metadata + CSV exists | `has_coverage` → **True** | **ORANGE/P0** |
| Zero previous close in returns | Coerced to `0.0` | **ORANGE** |
| Insufficient range history | Soft `NORMAL` | **ORANGE** |
| Naive session timestamps | Silently accepted | **ORANGE** |

---

## 16. Causality / Look-Ahead

| Feature | Finding |
|---------|---------|
| Swing confirmation | Requires `right_bars` future completed bars — correct fractal delay; verified |
| Indicators | Prefix recompute stable; evaluate on `bars[:T]` only for causal research |
| HTF | No engine enforcement — caller risk |
| Zones | Manual static — no future PA unless JSON updated |
| Phase | Uses already-materialized packs at `asof` |

**Verdict:** Swing delay documented and correct. **P0 gap:** no causal HTF builder.

---

## 17. Existing Test Quality (pre-verification)

| Area | Pre-existing quality |
|------|----------------------|
| Indicators / RVOL | Exact math — good |
| Zones / session / historical parse | Behavior — good |
| Feature trend/MTF | Scenario/smoke — weak (often identical HTF series) |
| Momentum | Mostly presence — weak |
| MarketState | Serialization + section availability — medium |

Verification suite closes the golden-vector gap for swings, MTF conflict, TSMOM, range overlap, BOS nature, dual zones, coverage bug.

---

# FINAL SCORECARD

| Component | Correctness | Research Readiness | Main Problem | Priority |
|-----------|-------------|--------------------|--------------|----------|
| Swing detection | GREEN | High for prices | No index/time | P1 |
| Swing model | YELLOW | Low for events | Price-only | P1 |
| HH/HL/LH/LL | YELLOW | Low | Prose only | P2 |
| BOS | ORANGE | Low | Lookback ≠ structure; unused | P1 |
| CHOCH | RED | None | Missing | P2 |
| Trend | GREEN | Medium | Strength is config constant | P0 (naming) |
| MTF | ORANGE | Low | No causal HTF bars | P0 |
| Momentum | GREEN | Medium | Hardcoded 20; zero coercion | P1 |
| Indicators | GREEN | High | Library dependency | P2 |
| Range expansion | ORANGE | Medium | Nested windows; soft NORMAL | P0 |
| Phase | ORANGE | Low | REVERSAL residual | P1 |
| Zones | YELLOW | Medium | Manual + dual path | P1 |
| Session | YELLOW | Medium | Naive TZ; no holidays | P1 |
| MarketState | YELLOW | Medium | Overclaim fields; unwired | P0 |
| Data quality | ORANGE | Medium | has_coverage; soft defaults | P0 |
| Causality | ORANGE | Medium | HTF caller-dependent | P0 |

---

# RECOMMENDED IMPLEMENTATION ORDER

## KEEP
- `SwingGenerator` fractal math (strict inequality, L/R windows)
- `PandasTAProvider` + custom RVOL
- `ReturnsGenerator` close-to-close (after invalid-price policy fix)
- `SessionManager` mega-session windows (after naive rejection)
- `ZoneEngine` distance/HTF query API
- MarketState packaging pattern (`status`, method_ids, JSON)

## FIX (before AI MarketState use)
1. **P0** Causal HTF bar construction / document that callers must supply causal HTF  
2. **P0** `HistoricalStorage.has_coverage` must not return True when metadata missing  
3. **P0** Range expansion insufficient history → unavailable (not NORMAL)  
4. **P0** Rename/document `structure.strength` as config score (not confidence)  
5. **P1** Reject or UTC-normalize naive timestamps in SessionManager / FeatureRepository  
6. **P1** Returns: do not coerce bad prices to 0.0  
7. **P1** Unify ChartAnalyzer vs ZoneEngine active-zone selection  
8. **P1** Mark zones as `source=manual` in MarketState  

## REPLACE
- BOSRule as “structure BOS” — replace with swing-referenced BOS or rename to lookback breakout  
- Phase REVERSAL residual — replace with explicit unknown/residual label  

## ADD
- Swing index + timestamp  
- Causal M1→HTF resampler  
- Explicit HH/HL events (only if SMC language required)  
- Wire MarketState into research logging (still no AI)  

## DEFER
- CHOCH  
- Auto zone detection  
- Holiday/DST exchange calendars  
- Liquidity engine  
- AI Market Analyst / LLM  
- Live execution  

---

## Do NOT implement the AI agent yet

MarketState is a faithful packager of **current** REX math, but several fields (`strength`, MTF agreement, phase reversal, zones) can **overstate** certainty. Fix P0 items and wire research evaluation first.
