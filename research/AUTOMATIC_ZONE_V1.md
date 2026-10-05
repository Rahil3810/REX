# Automatic Zone Generation V1

## What it means

Automatic Zone V1 detects **price-interest bands** from confirmed structural
`SwingEvent`s by clustering nearby swing prices.

- Swing-high clusters → `SUPPLY`
- Swing-low clusters → `DEMAND`

These are **automatically detected research annotations**, not proven
“institutional” supply/demand zones.

Method id: `swing_cluster_zone_v1`

## What it does NOT mean

- Not KDE / DBSCAN / ML / LLM zone detection
- Not order-block heuristics as the core definition
- Not volume profile
- Not confidence or probability
- Not live trading signals
- Not a replacement for manual zones

## Clustering definition

Only swings with `confirmation_index <= asof_index` and
`confirmation_time <= asof` are eligible.

For each kind separately, swings are sorted by price and greedily merged when:

```
next_price - cluster_max_price <= tolerance
```

Tolerance:

- Prefer `cluster_atr_multiple * causal_ATR(asof)`
- If ATR cannot be computed (insufficient bars): `absolute_price_tolerance`

ATR is computed on the causal bar prefix only.

## Zone-bound definition

- Multi-swing cluster: `[min(prices), max(prices)]`
- Single-swing cluster: expand by half-width
  `single_swing_half_width_atr_multiple * ATR`
  (or absolute fallback)

## Supply / demand definition

- Confirmed swing-high cluster → `ZoneKind.SUPPLY`
- Confirmed swing-low cluster → `ZoneKind.DEMAND`

This is classification by structural extreme type only.

## Freshness / mitigation / broken semantics

Evaluated causally from origin confirmation through asof:

| Status | Rule |
|--------|------|
| `fresh` | No close has entered the band |
| `tested` | At least one close inside the band; not broken |
| `broken` | SUPPLY: close strictly `> high`; DEMAND: close strictly `< low` |

- **Touches** may use wick overlap (`high/low` intersects band).
- **Breaks require close** — wick-only penetration does not break a zone.

## Score / strength meaning

Canonical `Zone.strength` remains a 0–10 **ranking integer**.

Automatic V1 formula (transparent, not confidence):

```
min(10, contributing_swings + touch_count // 2)
```

Broken zones are capped at `2`.

Raw evidence (counts, origin swing ids, departure/reaction, BOS association,
ATR used, tolerance) is stored separately in `ZoneEvidence` and must be
consulted to explain why a zone exists.

## Causal / as-of behavior

`AutomaticZoneGenerator.generate(..., asof=..., asof_index=...)` uses only the
bar prefix through asof and only confirmed swings known by asof.

Future bars appended after asof must not change historical generation results
for that asof.

## Integration

- `AutomaticZoneProvider` supplies `source=automatic` zones to `ZoneEngine`
- `ManualZoneProvider` unchanged (`source=manual`)
- `CompositeZoneProvider` can combine both for research
- Live BreakoutStrategy / SignalEngine paths are **not** wired to automatic zones

## Known limitations

- Clustering is price-distance only (no volume / session awareness)
- Single-swing bands depend on ATR/absolute half-width parameters
- Departure/reaction metrics are simple lookback heuristics
- BOS association is presence of `swing_bos_v1` on a contributing swing, not a
  full order-flow claim
- Gaps in M1 data are not “filled”

## Why KDE is deferred

KDE would be a **future candidate-generation method** behind the same
`ZoneCandidateGenerator` protocol. V1 prioritizes a deterministic, testable
swing-cluster definition before introducing density estimation bandwidth
choices and their research-safety complexity.
