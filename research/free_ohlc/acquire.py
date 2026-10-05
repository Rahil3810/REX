"""Acquire small free EURUSD OHLC samples for research (no production writes)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

# Public Kaggle dataset *sample* endpoint observed to return real ZIP bytes without
# interactive login in this environment (free evaluation sample only).
KAGGLE_ORKADD_EURUSD_1M_SAMPLE_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "orkadd/eurusd-1m-ohlcv-forex-historical-data"
)

DEFAULT_FILENAME = "EURUSD_1m.csv"


def download_kaggle_orkadd_eurusd_m1_sample(
    dest_dir: Path,
    *,
    url: str = KAGGLE_ORKADD_EURUSD_1M_SAMPLE_URL,
    timeout_seconds: float = 120.0,
    force: bool = False,
) -> Path:
    """Download the free Kaggle EURUSD 1m evaluation sample into ``dest_dir``.

    Returns path to ``EURUSD_1m.csv``. Does not write to ``data/historical/``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / DEFAULT_FILENAME
    if out.is_file() and out.stat().st_size > 0 and not force:
        return out

    req = Request(url, headers={"User-Agent": "rex-free-ohlc-research/1.0"})
    with urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310 — fixed HTTPS vendor URL
        payload = resp.read()

    if len(payload) < 1000:
        raise RuntimeError(f"download too small ({len(payload)} bytes); refusing")

    # Response is a ZIP containing EURUSD_1m.csv
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise RuntimeError("ZIP contained no CSV")
            names.sort(key=lambda n: (0 if "EURUSD" in n.upper() else 1, n))
            data = zf.read(names[0])
            # Drop leading marketing comment lines are fine to keep for parser.
            out.write_bytes(data)
    else:
        # Plain CSV fallback
        out.write_bytes(payload)

    if out.stat().st_size <= 0:
        raise RuntimeError("acquired file is empty")
    return out
