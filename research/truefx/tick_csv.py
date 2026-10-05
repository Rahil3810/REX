"""TrueFX historical tick CSV parsing helpers (research-only).

Documented community/vendor format for monthly archives:

    pair,timestamp,bid,ask

Example:

    EUR/USD,20241009 14:40:21.818,1.09476,1.09478

No volume column. Timestamps are millisecond wall-clock strings.
Official historical-download page does not restate timezone; do not convert.
"""

from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


TIMESTAMP_FORMATS = (
    "%Y%m%d %H:%M:%S.%f",  # millisecond / fractional seconds
    "%Y%m%d %H:%M:%S",  # whole seconds fallback
)


@dataclass(frozen=True)
class TrueFXTick:
    """One TrueFX top-of-book quote tick (research representation)."""

    pair: str
    timestamp: datetime  # naive source wall-clock; NOT converted
    bid: float
    ask: float

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")


def parse_truefx_timestamp(raw: str) -> datetime:
    text = raw.strip()
    if not text:
        raise ValueError("empty timestamp")
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized TrueFX timestamp: {text!r}")


def parse_truefx_tick_line(line: str) -> TrueFXTick | None:
    text = line.strip()
    if not text:
        return None
    # Header-ish rows occasionally appear in third-party copies; skip safely.
    lower = text.lower()
    if lower.startswith("pair,") or lower.startswith("symbol,"):
        return None
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(f"expected 4 CSV fields (pair,ts,bid,ask), got {len(parts)}: {text[:80]!r}")
    pair, ts_raw, bid_raw, ask_raw = parts
    bid = float(bid_raw)
    ask = float(ask_raw)
    return TrueFXTick(
        pair=pair.strip(),
        timestamp=parse_truefx_timestamp(ts_raw),
        bid=bid,
        ask=ask,
    )


def tick_prices_valid(tick: TrueFXTick) -> bool:
    if not (math.isfinite(tick.bid) and math.isfinite(tick.ask)):
        return False
    if tick.bid <= 0 or tick.ask <= 0:
        return False
    if tick.ask < tick.bid:
        return False
    return True


def iter_truefx_csv_lines(path: Path):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"ZIP contains no CSV: {path}")
            members.sort()
            with zf.open(members[0]) as raw:
                for line in raw:
                    yield line.decode("utf-8", errors="replace")
    else:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            yield from fh


def locate_truefx_files(data_dir: Path, symbol: str) -> list[Path]:
    """Locate local TrueFX monthly ZIP/CSV files for a symbol."""
    if not data_dir.is_dir():
        return []
    sym = normalize_symbol(symbol)
    patterns = [
        f"{sym}-*.zip",
        f"{sym}-*.csv",
        f"{sym}_*.zip",
        f"{sym}_*.csv",
        f"*{sym}*.zip",
        f"*{sym}*.csv",
    ]
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(data_dir.glob(pattern)):
            if path.is_file() and path.stat().st_size > 0 and path not in seen:
                # Skip README-like text
                if path.suffix.lower() not in {".zip", ".csv"}:
                    continue
                seen.add(path)
                found.append(path)
    return found


def in_date_range(ts: datetime, start: date | None, end: date | None) -> bool:
    d = ts.date()
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True
