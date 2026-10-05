# TrueFX research staging (EURUSD)

Isolated research data — **not** production `data/historical/`.

## Access (current)

- Historical downloads require a **free** TrueFX account:
  https://www.truefx.com/truefx-historical-downloads-2/
- There is **no** public unauthenticated historical download endpoint.
- Paid Professional/Institutional plans are for **live streaming**, separate from free historical ZIPs.
- Legacy `webrates.truefx.com` snapshot API currently returns an empty body.

## Manual download

1. Register / log in at truefx.com
2. Open Historical Downloads
3. Download one monthly EURUSD ZIP (e.g. `EURUSD-2026-01.zip`)
4. Place it in this directory
5. Run:

```bash
PYTHONPATH=. .venv/bin/python scripts/rex_truefx_probe.py \
  --symbol EURUSD \
  --start 2026-01-02 \
  --end 2026-01-02 \
  --data-dir research/data/truefx/EURUSD
```

## Format

Headerless CSV: `pair,timestamp,bid,ask`  
Timestamp: `YYYYMMDD HH:MM:SS.mmm`  
No volume column. Timezone: **confirm with vendor** (secondary sources claim GMT).
