# HistData research staging (EURUSD M1)

Isolated research data — **not** production `data/historical/`.

## Manual download (required)

HistData serves January 2024 via an interactive POST (`/get.php`) with a page token
(`tk`) that is empty in raw HTML and is not available for safe headless download.

1. Open:
   https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/eurusd/2024/1
2. Click download for:
   `HISTDATA_COM_ASCII_EURUSD_M1_202401.zip`
3. Place the ZIP (or the extracted CSV) in this directory:
   `research/data/histdata/EURUSD/M1/`

Expected names (any of these work for the probe):

- `HISTDATA_COM_ASCII_EURUSD_M1_202401.zip`
- `DAT_ASCII_EURUSD_M1_202401.csv` (typical extract name)

## Format (vendor spec)

- Separator: `;`
- Fields: `DateTime;Open;High;Low;Close;Volume`
- Timestamp: `YYYYMMDD HHMMSS` (seconds always `00` for M1)
- Timezone: Eastern Standard Time (EST) **without** DST adjustments
- Quotes: Bid OHLC

Then run:

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_histdata_m1_probe.py
```
