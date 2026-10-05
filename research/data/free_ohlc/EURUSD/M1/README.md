# Free OHLC research staging — EURUSD M1

Not production `data/historical/`.

## Recommended source

**Kaggle orkadd EURUSD 1m evaluation sample** (free):

- Dataset: https://www.kaggle.com/datasets/orkadd/eurusd-1m-ohlcv-forex-historical-data
- Format: `time,open,high,low,close,volume` with ISO-8601 `Z` (UTC)
- Volume: treat as **tick volume**, not exchange volume
- Coverage (sample): ~2026-01-04 → 2026-07-03
- Full commercial archive lives on ork.ad — we only use the free sample

## Acquire + probe

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_free_ohlc_probe.py \
  --symbol EURUSD \
  --timeframe M1 \
  --start 2026-01-05 \
  --end 2026-01-07 \
  --data-dir research/data/free_ohlc/EURUSD/M1 \
  --acquire
```

## Volume / quality caveat

Volume in this sample is **tick volume** (activity count), not exchange volume.

Some rows violate OHLC integrity (open/close outside high/low). For research smokes:

```bash
... --skip-invalid-ohlc
```

That **drops** bad rows; it never repairs or fabricates prices.
