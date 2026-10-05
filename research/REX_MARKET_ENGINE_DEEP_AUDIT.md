# REX MARKET ENGINE DEEP AUDIT

**Date:** 2026-08-29  
**Mode:** Hostile conceptual validation (read-only production code)  
**Prior report:** `research/REX_MARKET_ENGINE_VERIFICATION_REPORT.md` (58 golden-vector tests, PASS)  
**This audit suite:** `tests/test_market_engine_deep_audit.py` (10 conceptual tests) + prior verification suite  
**Combined result:** **68 tests PASS** (`.venv`)  
**Production code modified:** No

This audit asks a harder question than the first verification:

> Do the current implementations represent the trading concepts REX claims to represent?

Passing math tests proves “code matches its algorithm.”  
This report distinguishes **mechanically correct** from **conceptually appropriate**.

---

## 1. Executive Summary

REX has a **real, partially correct research feature spine** (`FeatureRepository` → packs → Views → `MarketStateBuilder`) and a **separate live/demo trading spine** (`main.py` → `SignalEngine` → `BreakoutStrategy` + `ChartAnalyzer`) that does **not** use that feature spine.

| Claim | Reality |
|-------|---------|
| Structural swing foundation | Strict fractal L/R extrema — **mathematically sound**, but **price-only** model is insufficient for event reasoning |
| Market structure BOS | `BOSRule` is **lookback max/min breakout**, not fractal-swing BOS; **unused** by strategies |
| CHOCH | **Not implemented** |
| HH / HL / LH / LL | **Prose only** inside trend reason strings |
| Trend strength / confidence | Config lookup (`85` / `35` / `0`) — **not** magnitude or probability |
| Multi-timeframe structure | Agreement **score** exists; REX **does not** construct causal HTF bars |
| Momentum | Fixed **20-bar cumulative simple return** — not sophisticated TSMOM |
| Phase REVERSAL | **Residual fallback** — **NOT A REVERSAL DETECTOR** |
| Zones | Manual JSON; **ChartAnalyzer** and **ZoneEngine** can disagree |
| MarketState | Packaging / inference layer for research — **not** wired into trading |
| Research safety | Several **silent defaults** can invent valid-looking states from bad/missing data |

**Final classification:** **Research Ready with Restrictions**

Not Production Ready. Not Incomplete (core primitives exist). Not merely a Prototype (tests prove deterministic behavior). Usable for research **only** when restrictions in §6–§9 are respected.

---

## 2. Repository Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ LIVE / DEMO PATH (actually used by main.py)                     │
│  MockDataFeed → SignalEngine → BreakoutStrategy                 │
│                 → ChartAnalyzer (zones) + SessionManager (log)  │
│  ✗ FeatureRepository  ✗ SwingGenerator  ✗ MarketState  ✗ BOSRule│
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ BACKTEST PATH (research execution spine)                        │
│  BacktestRunner → strategy.generate_signals(causal prefix)      │
│  Strategies: Breakout / LiquiditySweep (+ placeholders)         │
│  ✗ FeatureRepository  ✗ MarketState  ✗ BOSRule                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ FEATURE / MARKETSTATE PATH (research packaging; tests primarily)│
│  bars_by_tf (caller-supplied)                                   │
│    → FeatureRepository.materialize → FeatureContext packs       │
│    → TrendView / MomentumView / VolatilityView / PhaseView      │
│    → MarketStateBuilder.build → MarketState                     │
│  Generators: SwingGenerator, ReturnsGenerator,                  │
│              RangeExpansionGenerator, Indicator pack            │
└─────────────────────────────────────────────────────────────────┘
```

**What the trading/backtesting system uses today:** zone breakout / liquidity-sweep rules on candle history — **not** the market-structure feature engine.

---

## 3. Detailed Findings (Sections 1–18)

### 3.1 Swing Detection

| Field | Content |
|-------|---------|
| **Component** | Swing detection |
| **File** | `core/features/generators/swings.py` |
| **Class/function** | `SwingGenerator.generate`, `_find_swings` |
| **Intended behavior** | Confirmed structural swings with left/right confirmation |
| **Actual behavior** | For `index ∈ [left, len-right)`: high is swing iff strictly `>` all highs in left+right windows; low iff strictly `<` all lows. Defaults `left=2`, `right=2`. Output = price tuples only. `instrument` / `entry_timeframe` ignored. |
| **Test scenario** | Equal double-top highs (15,15) with L=R=2; right-boundary candidates; golden vector from verification suite |
| **Expected** | No swing on equal peaks; last `right` bars never confirmed; exact prices match hand math |
| **Actual** | Matches (`DeepSwingFoundationTests`, verification suite) |
| **Verdict** | **GREEN** for fractal math; **YELLOW** as sole foundation for a full SMC engine |
| **Research risk** | Double tops/bottoms silently disappear under strict inequality; confirmation delay is real but not timestamped |
| **Exact change eventually required** | KEEP math; ADD bar index + candidate time + confirmation time |
| **Priority** | P1 |

**Checks A–I**

| Check | Result |
|-------|--------|
| A. Swing high needs L+R bars | YES |
| B. Swing low symmetric | YES |
| C. Equal highs/lows | No swing (strict) |
| D. Boundary candles | Last `right` bars cannot confirm |
| E. Causal once right closed | YES for closed series |
| F. Forming candle as confirmed | No — excluded by range |
| G. Nearby swings | Sensible under strict fractal; equals suppress |
| H. Window only intended bars | YES (`index±L/R` only) |
| I. Appropriate for REX structure? | Valid **primitive**, insufficient **alone** for event-level structure |

**Answer: Is this a valid foundation for a structural market engine?**  
**Yes, as a price-extremum primitive.** It is **not** yet a complete structural foundation because confirmed swings cannot be referenced as events (see §3.2).

---

### 3.2 Swing Model

| Field | Content |
|-------|---------|
| **Component** | Swing model / serialization |
| **File** | `swings.py` (`TimeframeSwings`, `SwingFeatures`); `packs/base.py` (`StructurePack`); `market_state/models.py` (`TimeframeSwingSnapshot`) |
| **Intended** | Enough identity for downstream structural reasoning |
| **Actual** | `timeframe` + `swing_highs: tuple[float]` + `swing_lows: tuple[float]` only |
| **Lost** | candle index, timestamp, confirmation time, swing ID, high/low as typed events, uniqueness when prices collide |
| **Can answer “which candle?”** | NO |
| **Can answer “when confirmed?”** | NO |
| **Can answer “which swing did BOS break?”** | NO (and BOSRule does not use swings anyway) |
| **Can answer “previous structural high?”** | Only as last price in tuple — ambiguous if duplicates |
| **Timeframe ownership** | YES via key |
| **Verdict** | **YELLOW** |
| **Priority** | P1 |

---

### 3.3 HH / HL / LH / LL

| Field | Content |
|-------|---------|
| **Component** | Structure labels |
| **File** | `core/features/views/trend.py` — `_classify_swings` |
| **Search** | No HH/HL/LH/LL enum, model, or event type in repository |
| **Actual** | Boolean all-rising / all-falling over last `minimum_swings` highs **and** lows → `BULLISH` / `BEARISH` / else `RANGING`; prose embeds “higher highs” etc. |
| **Scenarios** | HH+HL → BULLISH; LH+LL → BEARISH; HH+LL mixed → RANGING; no explicit “failed HL” event |
| **Verdict** | **YELLOW** — inferred for trend enum; **not** explicit structure events |
| **Research risk** | Consumers may treat reason strings as structured evidence |
| **Change** | ADD typed structure events **or** document prose-only |
| **Priority** | P2 |

REX can explicitly represent: `BULLISH` / `BEARISH` / `RANGING` / `UNKNOWN`.  
REX cannot explicitly represent: HH, HL, LH, LL as first-class objects.

---

### 3.4 BOS

| Field | Content |
|-------|---------|
| **Component** | Break of Structure |
| **File** | `strategies/rules/bos_rule.py` — `BOSRule.detect` |
| **Docstring claim** | “Close above previous swing high / below previous swing low” |
| **Actual definition** | **Definition B:** close breaks max-high / min-low of `candles[-lookback-1:-1]` (default lookback=10). Requires caller `bullish`/`bearish` flags. Wick-only insufficient. Strength = pip-ish heuristic. `broken_swing_index` is index into the **slice**, not absolute bar index. |
| **Definition A (structural)** | Close breaks most recent **confirmed fractal** swing — **NOT implemented** |
| **Test** | Fractal SHs `(15,14)`; lookback max `16` (non-fractal). Close `16.5` → BOS breaks `16`. Close `15.5` breaks structural `14` but **not** lookback max → **no BOS** (`DeepBOSSemanticTests`) |
| **Repeated BOS** | Same lookback extremum can re-trigger every bar while close remains beyond it (no swing-consumption) |
| **Against trend** | Only if caller sets flags that way |
| **Connected?** | **DEAD** for strategies — AST scan: no strategy imports `BOSRule` |
| **Verdict** | **ORANGE** (works as breakout; wrong abstraction for “BOS”) / **DEAD** in trading path |
| **Priority** | P1 |

**Conclusion:** BOS is implemented as **lookback breakout detection**, not market-structure BOS.

---

### 3.5 CHOCH

| Field | Content |
|-------|---------|
| **Component** | Change of Character |
| **Search** | No `choch*.py`; `StructurePack` = `{pack_id, swings}` only; legacy `core/market_structure/choch.py` deleted |
| **Verdict** | **RED / STUB (absent)** — NOT IMPLEMENTED |
| **Required before safe CHOCH** | Swing events with index/time; explicit HH/HL stream; prior trend state; causal confirmation rules; definition of which swing fails |
| **Priority** | P2 (defer until swing model enriched) |

---

### 3.6 Trend

| Field | Content |
|-------|---------|
| **Component** | Trend classification & strength |
| **File** | `core/features/views/trend.py` — `_classify_swings`, `_trend_strength`, `_multi_timeframe_agreement` |
| **trend** | Enum from consecutive swing price comparisons |
| **strength** | Config table: aligned=`85`, ranging=`35`, unknown=`0` — **identical for tiny and huge structures** (`DeepTrendStrengthTests`) |
| **confidence** | **Does not exist** as a computed field |
| **score (MTF)** | Separate agreement score from config (`85/55/35/0`) |
| **Verdict** | **YELLOW** — trend direction logic is coherent; “strength” naming is misleading |
| **Priority** | P0 (naming/docs before any consumer treats 85 as confidence) |

**85 is a configuration constant (aligned_structure_score), not confidence, probability, or quality.**

---

### 3.7 Multi-Timeframe

| Field | Content |
|-------|---------|
| **Component** | MTF agreement |
| **File** | `FeatureConfig` mapping; `TrendView._multi_timeframe_agreement`; `FeatureRepository.materialize` |
| **How HTF candles are produced** | **Caller supplies** each TF. Repository only symbol-filters + sorts. **No resampler** in production code (`DeepConnectivityTests`). |
| **Incomplete HTF candle** | Not handled by REX — caller problem |
| **Gaps / timezone / leakage** | No engine enforcement |

**Critical answer:**  
**Can REX itself guarantee that an H1 feature evaluated at 10:37 does not use information from 10:38–10:59?**  
**NO.** REX cannot guarantee HTF causality. If the caller feeds a fully formed H1 bar that includes future M1, features will use it.

| Verdict | **ORANGE** |
| Priority | **P0** |

---

### 3.8 Momentum

| Field | Content |
|-------|---------|
| **Component** | `ts_mom_v1` |
| **File** | `ReturnsGenerator`; `MomentumView.project`; config key `"momentum"` historically maps to **range expansion** (naming trap); `MomentumRule` is empty placeholder |
| **Measures** | Cumulative **simple** close-to-close return over `min(20, n)` bars |
| **Log returns** | Computed in pack; **unused** by `ts_mom_v1` |
| **Vol adjustment** | None |
| **Normalization** | None (`strength = abs(sum)`) |
| **Verdict** | **YELLOW** — correct simple TSMOM; **not** sophisticated momentum |
| **Priority** | P1 |

Do not call this sophisticated momentum. It is a fixed-window cumulative return sign.

---

### 3.9 RSI / MACD / EMA / ATR / RVOL

| Indicator | Provider | Notes | Verdict |
|-----------|----------|-------|---------|
| EMA / RSI / ATR / MACD | `PandasTAProvider` → `pandas_ta_classic` | Library formulas; pack takes last non-NaN scalar; warmup → `None` | **GREEN** (with library trust boundary) |
| MACD hist | Verified ≈ macd − signal | Independent check in verification suite | **GREEN** |
| RVOL | Local in `IndicatorEngine` | current / mean(**previous** N); NaN if insufficient / missing / zero baseline | **GREEN** |
| SMA | Exact golden vectors | Trustworthy | **GREEN** |

**Research trust:** Acceptable for research scalars if library version is pinned and NaNs are treated as unavailable. Exact Wilder vs SMA RSI seeding is library-dependent — not re-derived in REX.

| Priority | P2 (pin versions; document trust boundary) |

---

### 3.10 Volatility / Range Expansion

| Field | Content |
|-------|---------|
| **File** | `core/features/generators/range_expansion.py` |
| **Formula** | `ratio = mean(|c-o| recent) / mean(|c-o| historical)` |
| **Windows** | `recent = bars[-recent:]` ⊆ `historical = bars[-historical:]` — **intentional nested overlap**, not exclusive prior baseline |
| **Insufficient bars** | Returns **`NORMAL`**, `ratio=None` — silent soft default |
| **Zero historical body** | `LOW` |
| **Verdict** | **ORANGE** |
| **Priority** | P0 (soft NORMAL); P1 (exclusive baseline if research needs it) |

Unavailable data **can** become a valid-looking **NORMAL** regime.

---

### 3.11 Market Phase

| Field | Content |
|-------|---------|
| **File** | `core/features/views/phase.py` — `PhaseView.project` |
| **Decision tree** | (1) compression via range score ≤35 → (2) ranging/unknown → RANGE → (3) pullback (monotonic closes against trend) → (4) strength ≥70 → TREND → (5) else **REVERSAL** |
| **REVERSAL** | Residual: `"Directional structure without strong-trend strength."` No `detect_reversal`. With default strength 85, branch is nearly unreachable. |
| **Verdict** | **ORANGE** |

**Explicit classification:** Phase REVERSAL is **NOT A REVERSAL DETECTOR**.

| Priority | P1 |

---

### 3.12 Zones

| Field | Content |
|-------|---------|
| **Files** | `ZoneEngine`, `ManualZoneProvider`, `ChartAnalyzer`, zone JSON, optional Feature pack |
| **Who creates zones** | Humans / JSON — **never market-derived** (`ManualZoneProvider` docstring) |
| **strength / timeframe** | Manual attributes |
| **Provenance** | Not retained as `source=manual` in MarketState |
| **Overlap selection** | ZoneEngine: strongest inside; ChartAnalyzer: **first** containing |
| **Disagreement** | Proven: price 1.11 → engine id=2, chart id=1 |
| **MarketState** | Uses ZoneEngine path when injected; live SignalEngine uses ChartAnalyzer |
| **Verdict** | **YELLOW** (queries OK) / dual-path risk **ORANGE** for consistency |
| **Priority** | P1 |

---

### 3.13 Session

| Field | Content |
|-------|---------|
| **File** | `core/session_manager.py` |
| **Windows** | Fixed UTC mega-sessions (London 08–17, NY 13–22, …) — **not DST-shifting exchange hours** |
| **Naive datetime** | `astimezone(IST)` silently uses system local TZ — **accepted** |
| **Calendar** | `AlwaysOpenCalendar` always open — no weekends/holidays |
| **Boundaries** | start inclusive, end exclusive |
| **Verdict** | **YELLOW** |
| **Priority** | P1 |

Timestamps are **not** interpreted safely for research that assumes UTC-only or DST-aware London open.

---

### 3.14 MarketState

| Field | Content |
|-------|---------|
| **Files** | `core/market_state/{models,builder}.py` |
| **What it is** | Immutable packaging of View/pack outputs with section status |
| **A faithful snapshot?** | Faithful to **current** math — including misleading names |
| **B inference layer?** | Yes — phase heuristic, MTF score, strength table, soft defaults |
| **C AI-ready representation?** | Docstring says “AI-facing”; **unsafe** until P0 naming/causality/soft-defaults fixed; **unwired** to trading |

**Overclaim vectors**

| Field | Risk |
|-------|------|
| `structure.strength` | Looks like confidence; is config constant |
| `phase=REVERSAL` | Residual, not detection |
| MTF agreement prose | Assumes caller HTF causality |
| `liquidity` | Always `unsupported` |
| zones | No manual provenance flag |
| swings in snapshot | Price-only |

| Verdict | **YELLOW** |
| Priority | P0 |

Proven classification: **B (inference/packaging layer)** with partial A fidelity to packs, **not** C.

---

### 3.15 Data Quality

| Case | Behavior | Verdict |
|------|----------|---------|
| Duplicate / invalid OHLC | Parser rejects (verification) | GREEN |
| Zero/negative prior close in returns | Coerced to `0.0` return | ORANGE |
| Missing volume / RVOL | NaN → pack None | GREEN |
| Insufficient range history | Soft **NORMAL** | ORANGE / P0 |
| `HistoricalStorage.has_coverage` | Missing `.meta.json` + non-empty CSV → **True**; only checks `start_date.year` file | **RED** for coverage claims |
| Insufficient swings | Trend UNKNOWN | GREEN |

Bad data **can** silently become valid-looking features (returns 0.0, range NORMAL, false coverage).

---

### 3.16 Causality / Look-Ahead

| Feature | At time T | Valid confirmation delay? | Invalid leakage? |
|---------|-----------|---------------------------|------------------|
| Swings | Needs `right_bars` closed bars after candidate | YES | Model does **not** record confirmation time → consumers may treat candidate time as known |
| Returns / indicators | Uses bars provided at materialize | If caller prefixes to T | If full series passed, look-ahead possible |
| Range expansion | Same | Same | Soft NORMAL hides insufficiency |
| Phase | Uses packs at asof | Dependent | Residual REVERSAL overclaim |
| MTF | Depends on caller HTF bars | N/A | **Primary leakage risk** |
| Zones | Static manual | N/A | Only if JSON anticipates future |
| Session | Clock time only | N/A | Naive TZ ambiguity |

---

### 3.17 Connectivity

| Consumer | FeatureRepository | MarketState | SwingGenerator | BOSRule | ChartAnalyzer |
|----------|-------------------|-------------|----------------|---------|---------------|
| `main.py` / `SignalEngine` | No | No | No | No | Yes |
| `BacktestRunner` | No | No | No | No | Via strategy zones only |
| Strategies (breakout/sweep) | No | No | No | No | Indirect |
| Unit/research tests | Yes | Yes | Yes | Verification only | Yes |
| `MomentumRule` / `SessionRule` / `RetestRule` | Placeholder / unused | — | — | — | — |

**Dead / disconnected:** `BOSRule`, CHOCH (absent), `LiquidityView` unsupported, MarketState from live path, FeatureRepository from BacktestRunner.

**Answer: What market engine is the actual trading/backtesting system using today?**  
**Zone-centric breakout / liquidity-sweep on causal candle prefixes — not the FeatureRepository market-structure engine.**

---

### 3.18 Test Quality

| Suite | Proves | Limitation |
|-------|--------|------------|
| `test_market_engine_verification.py` (58) | Independent golden vectors, BOS≠fractal, soft NORMAL, dual zones, has_coverage bug, causality of right window | Does not wire MarketState → SignalEngine |
| `test_market_engine_deep_audit.py` (10) | Conceptual: strength constant, structural BOS miss, no resampler, REVERSAL residual, BOS unused | AST-based connectivity |
| Pre-existing feature/MTF tests | Often smoke / identical HTF series | False confidence risk |
| Indicator tests | Behavioral + some exact | Library formula not fully proven |

**Do not count test quantity as concept correctness.** Many older tests prove “runs / returns enum.” Verification + deep audit prove semantics for audited components.

---

## 4. Function-by-Function Verdict Table

| Component | File | Function | Purpose | Actual Behavior | Conceptually Correct? | Tested? | Verdict | Risk | Priority |
|-----------|------|----------|---------|-----------------|----------------------|---------|---------|------|----------|
| Swing detect | `generators/swings.py` | `_find_swings` | Confirmed swings | Strict L/R fractal prices | Yes (as fractal) | Yes | GREEN | Low math / high event gap | P1 |
| Swing generate | `generators/swings.py` | `generate` | Multi-TF swings | Per-TF fractal; ignores instrument | Yes | Yes | GREEN | Caller TF trust | P2 |
| Swing model | `swings.py` | `TimeframeSwings` | Structure identity | Prices only | No for events | Yes | YELLOW | Event referencing | P1 |
| Structure pack | `packs/base.py` | `StructurePack` | Structure features | Swings only | Limited | Yes | YELLOW | No BOS/CHOCH | P2 |
| HH/HL labels | `views/trend.py` | `_classify_swings` | Structure labels | Prose + enum | Partial | Yes | YELLOW | Over-read prose | P2 |
| Trend strength | `views/trend.py` | `_trend_strength` | Strength | Config constant | No as confidence | Yes | YELLOW | Overclaim | P0 |
| MTF score | `views/trend.py` | `_multi_timeframe_agreement` | HTF confirm | Enum equality score | Score OK; causality no | Yes | ORANGE | Look-ahead | P0 |
| Feature repo | `repository.py` | `materialize` | FeatureContext | Normalize + packs | Yes as materializer | Yes | GREEN | No HTF build | P0 |
| BOS | `rules/bos_rule.py` | `detect` | Structural BOS | Lookback breakout | No | Yes | ORANGE | Misnamed; DEAD | P1 |
| CHOCH | — | — | CHoCH | Absent | — | Search | RED | Missing | P2 |
| Returns | `generators/returns.py` | `generate` | Simple/log returns | Close-to-close; 0 coerce | Partial | Yes | YELLOW | Silent 0 | P1 |
| Momentum | `views/momentum.py` | `ts_mom_v1` | Momentum | Sum 20 simple returns | Yes as simple | Yes | YELLOW | Oversell name | P1 |
| MomentumRule | `rules/momentum_rule.py` | — | Strategy mom | Placeholder | — | — | STUB | Dead | P3 |
| Range expand | `generators/range_expansion.py` | `generate` | Vol regime | Nested windows; soft NORMAL | Weak | Yes | ORANGE | False NORMAL | P0 |
| Phase | `views/phase.py` | `project` | Lifecycle | Residual REVERSAL | No for reverse | Yes | ORANGE | Mislabel | P1 |
| Indicators | `pandas_provider.py` | EMA/RSI/ATR/MACD | TA | Library | Yes w/ trust | Yes | GREEN | Dependency | P2 |
| RVOL | `indicator_engine.py` | `relative_volume` | Rel volume | Prior baseline | Yes | Yes | GREEN | Low | P3 |
| ZoneEngine | `zones/engine.py` | queries | Zone query | Manual + strongest | Query OK | Yes | YELLOW | Dual path | P1 |
| ChartAnalyzer | `chart_analyzer.py` | `analyze` | Zone context | First-inside | Different semantics | Yes | YELLOW | Disagree | P1 |
| Session | `session_manager.py` | `get_current_session` | Session label | Fixed UTC; naive OK | Partial | Yes | YELLOW | TZ/DST | P1 |
| Coverage | `historical/storage.py` | `has_coverage` | Data complete? | Meta-missing → True | No | Yes | RED | False coverage | P0 |
| MarketState | `market_state/builder.py` | `build` | Snapshot | Packages Views | Packaging OK | Yes | YELLOW | Overclaim; unwired | P0 |
| LiquidityView | `views/liquidity.py` | — | Liquidity | Unsupported | — | Yes | STUB | — | P3 |
| SignalEngine | `signal_engine.py` | run loop | Live signals | Breakout only | N/A | Yes | DEAD* | Ignores feature spine | — |
| BacktestRunner | `backtest_runner.py` | `run` | Research trades | Strategy candles only | Causal for strat | Yes | DEAD* | Ignores feature spine | — |

\*DEAD relative to FeatureRepository/MarketState — not dead as executors.

---

## 5. Market Structure Specific Verdict

| Question | Answer |
|----------|--------|
| Are swings correct? | **Yes** as strict fractal L/R extrema |
| Is the swing model sufficient? | **No** — prices only; cannot support event BOS/CHOCH safely |
| Are HH/HL/LH/LL explicit? | **No** — prose + trend enum only |
| Is BOS true structural BOS? | **No** — lookback breakout; unused |
| Is CHOCH implemented? | **No** |
| Is trend meaningful? | **Directionally yes**; strength is **not** meaningful as confidence |
| Is MTF causal? | **Not guaranteed by REX** |

---

## 6. Research Safety Verdict

### Look-ahead risks
- Caller-supplied HTF bars (primary)
- Swing confirmation time not modeled (semantic mis-timing risk)
- Evaluating indicators on full series instead of prefix

### Silent defaults
- Range expansion insufficient → **NORMAL**
- Returns bad prior close → **0.0**
- Session naive datetime → system local TZ
- `has_coverage` missing metadata → **True**

### Data integrity risks
- Single-year coverage check
- No holiday/weekend rejection (`AlwaysOpenCalendar`)
- Zero-volume / zero-body edge cases partially handled

### Information loss
- Swing index/time/ID
- Explicit structure events
- Zone provenance
- Full return series in MarketState (by design)

### Disconnected components
- FeatureRepository / MarketState / SwingGenerator vs live+backtest
- BOSRule orphan
- MomentumRule / RetestRule placeholders
- Liquidity unsupported

---

## 7. What REX Actually Knows Today

At FeatureContext / MarketState materialization time (research path only), REX knows:

1. **Per-TF fractal swing high/low prices** (strict L/R), chronological order  
2. **Entry trend enum** from consecutive swing price directions  
3. **Config table “strength”** (85/35/0)  
4. **MTF agreement score** if caller provided matching TF keys  
5. **Simple + log return series** (and 20-bar cumulative simple “momentum”)  
6. **Body-size range expansion ratio** (or soft NORMAL)  
7. **Phase heuristic label** (compression / range / pullback / trend / residual “reversal”)  
8. **Last indicator scalars** (EMA/RSI/ATR/MACD/RVOL) when engine present  
9. **Manual zone book queries** when ZoneEngine injected  
10. **Mega-session label** from clock time  
11. Explicit **liquidity unsupported**

Live/demo and default backtests know primarily:

1. Candle history prefixes  
2. Manual zones via ChartAnalyzer / BreakoutRule  
3. Optional liquidity-sweep rule behavior  

---

## 8. What REX Does NOT Know

- Confirmed swing **events** (index, time, confirmation time, ID)  
- Explicit **HH/HL/LH/LL** objects  
- True structural **BOS** against fractal swings  
- **CHOCH**  
- Causal **M1→HTF** bars constructed by REX  
- Real **trend confidence / magnitude**  
- Sophisticated / vol-adjusted **momentum**  
- Positive-evidence **reversal** detection  
- Market-derived **zones**  
- Holiday / DST-accurate session economics  
- Whether historical partitions truly cover a range when metadata is missing  
- Anything about liquidity beyond “unsupported”  
- Feature/MarketState state inside **production signal/backtest** paths  

---

## 9. Recommended Implementation Order

Engineering only — **no AI agents**.

1. **P0** Causal HTF construction **or** hard documentation + fail-closed when HTF missing/incomplete  
2. **P0** Fix `HistoricalStorage.has_coverage` (missing meta ≠ covered; multi-year)  
3. **P0** Range expansion: insufficient → unavailable (not NORMAL)  
4. **P0** Rename/document `structure.strength` as config score; never “confidence”  
5. **P1** Enrich swing model (index + timestamps + confirmation time)  
6. **P1** Replace or rename `BOSRule`; optionally implement swing-referenced BOS after (5)  
7. **P1** Unify ChartAnalyzer vs ZoneEngine active-zone selection; mark zones `source=manual`  
8. **P1** Reject naive datetimes (or force UTC) in SessionManager  
9. **P1** Returns: invalid prices → unavailable, not 0.0  
10. **P1** Rename Phase residual away from REVERSAL  
11. **P1** Wire FeatureContext/MarketState into **research logging** on BacktestRunner (still no AI)  
12. **P2** Explicit HH/HL events if SMC language required; then CHOCH  
13. **P2** Configurable momentum lookback; pin indicator library versions  
14. **P3** Holiday calendar; auto zones; live wiring of MarketState  

---

## 10. Final Classification

### **Research Ready with Restrictions**

**Evidence (not optimism):**

- Swing math, returns, indicators, RVOL, and several pack builders are deterministic and independently tested.  
- Market-structure **language** (BOS, CHOCH, HH/HL, reversal, strength-as-confidence, causal MTF) is **partially missing, misnamed, or caller-dependent**.  
- The feature/MarketState spine is **real but disconnected** from the system that actually generates trade signals today.  
- Silent defaults (`NORMAL`, false coverage, strength=85) create **false research confidence**.

**Restrictions for any research use today:**

1. Do not treat `strength` as confidence.  
2. Do not treat phase `REVERSAL` as reversal detection.  
3. Do not treat `BOSRule` as structural BOS.  
4. Supply only causally closed HTF bars (REX will not enforce this).  
5. Do not trust `has_coverage` without `.meta.json`.  
6. Do not assume FeatureRepository outputs affect live/backtest strategies.  
7. Treat zones as manual annotations with dual-path selection risk.

---

## Appendix A — Audit Test Evidence

| Suite | Count | Result |
|-------|------:|--------|
| `tests/test_market_engine_verification.py` | 58 | PASS |
| `tests/test_market_engine_deep_audit.py` | 10 | PASS |
| **Total** | **68** | **PASS** |

Deep-audit tests specifically prove: equal-peak suppression; missing confirmation fields; lookback BOS ≠ fractal BOS; structural break without lookback break missed; strength invariant to magnitude; REVERSAL residual; no production resampler; BOS unused by strategies.

---

## Appendix B — Relation to First Verification Report

The first report established: **many functions behave correctly according to their current code.**

This deep audit establishes: **several of those correct functions implement the wrong or weak abstraction for the claimed trading concept**, and **the market engine that trades/backtests today is not the FeatureRepository structure engine.**

Use both reports together. Do not inflate readiness because 68 tests pass.
