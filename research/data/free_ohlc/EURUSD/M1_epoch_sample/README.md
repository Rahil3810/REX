# Epoch-ms OHLC sample (compatibility)

Copy of `download/eurusd-m1-bid-2026-08-20-2026-08-21.csv`.

Format: `timestamp,open,high,low,close` (Unix epoch milliseconds, assumed UTC).
No volume column.

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_free_ohlc_probe.py \
  --symbol EURUSD --timeframe M1 \
  --start 2026-08-20 --end 2026-08-20 \
  --data-dir research/data/free_ohlc/EURUSD/M1_epoch_sample
```
