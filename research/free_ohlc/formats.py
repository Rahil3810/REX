"""Parsers for free/public OHLC CSV formats (research-only).

Supported formats
-----------------
1. ``iso_z_ohlcv`` (Kaggle orkadd-style):
   ``time,open,high,low,close,volume`` with ISO-8601 timestamps ending in ``Z``.
   Timezone: confirmed UTC (``Z``).

2. ``epoch_ms_ohlc`` (simple public/export style):
   ``timestamp,open,high,low,close`` with Unix epoch milliseconds.
   Timezone: treated as UTC epoch ms (documented assumption).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path


class VolumeSemantics(str, Enum):
    NONE = "none"
    TICK_VOLUME = "tick_volume"
    UNKNOWN = "unknown"


class TimezonePolicy(str, Enum):
    CONFIRMED_UTC = "CONFIRMED_UTC"
    ASSUMED_UTC_EPOCH_MS = "ASSUMED_UTC_EPOCH_MS"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


@dataclass(frozen=True)
class FreeOhlcBar:
    """Research OHLC row prior to canonical Bar conversion."""

    timestamp: datetime  # naive UTC wall clock after explicit policy
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    volume_semantics: VolumeSemantics
    source_timezone_policy: TimezonePolicy
    source_format: str


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")


def ohlc_valid(open_: float, high: float, low: float, close: float) -> bool:
    vals = (open_, high, low, close)
    if not all(math.isfinite(v) for v in vals):
        return False
    if not all(v > 0 for v in vals):
        return False
    if high < low:
        return False
    if not (low <= open_ <= high):
        return False
    if not (low <= close <= high):
        return False
    return True


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_iso_z_ohlcv_line(line: str) -> FreeOhlcBar | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    lower = text.lower()
    if lower.startswith("time,") or lower.startswith("timestamp,"):
        return None
    parts = text.split(",")
    if len(parts) != 6:
        raise ValueError(f"iso_z_ohlcv expects 6 fields, got {len(parts)}: {text[:80]!r}")
    ts_raw, o, h, l, c, v = parts
    raw = ts_raw.strip()
    # Refuse naive timestamps — require Z or explicit numeric offset.
    has_tz = raw.endswith("Z") or raw.endswith("z") or ("+" in raw[10:]) or (
        raw.count("-") >= 3 and raw.rfind("-") > 10
    )
    if not has_tz:
        raise ValueError(f"iso_z_ohlcv timestamp missing timezone: {ts_raw!r}")
    aware = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
    if aware.tzinfo is None:
        raise ValueError(f"iso_z_ohlcv timestamp is naive (refusing): {ts_raw!r}")
    vol = float(v)
    return FreeOhlcBar(
        timestamp=_to_naive_utc(aware),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        volume=vol,
        volume_semantics=VolumeSemantics.TICK_VOLUME,
        source_timezone_policy=TimezonePolicy.CONFIRMED_UTC,
        source_format="iso_z_ohlcv",
    )


def parse_epoch_ms_ohlc_line(line: str) -> FreeOhlcBar | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    lower = text.lower()
    if lower.startswith("timestamp,") or lower.startswith("time,"):
        return None
    parts = text.split(",")
    if len(parts) != 5:
        raise ValueError(f"epoch_ms_ohlc expects 5 fields, got {len(parts)}: {text[:80]!r}")
    ts_raw, o, h, l, c = parts
    ms = int(float(ts_raw))
    aware = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return FreeOhlcBar(
        timestamp=_to_naive_utc(aware),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        volume=None,
        volume_semantics=VolumeSemantics.NONE,
        source_timezone_policy=TimezonePolicy.ASSUMED_UTC_EPOCH_MS,
        source_format="epoch_ms_ohlc",
    )


def detect_format(sample_lines: list[str]) -> str:
    for line in sample_lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        lower = text.lower()
        if lower.startswith("time,") or lower.startswith("timestamp,"):
            if "volume" in lower:
                return "iso_z_ohlcv"
            return "epoch_ms_ohlc"
        parts = text.split(",")
        if len(parts) == 6 and ("T" in parts[0] or "Z" in parts[0].upper()):
            return "iso_z_ohlcv"
        if len(parts) == 5 and parts[0].replace(".", "", 1).isdigit():
            return "epoch_ms_ohlc"
    raise ValueError("unable to detect free OHLC CSV format from sample lines")


def parse_line(line: str, fmt: str) -> FreeOhlcBar | None:
    if fmt == "iso_z_ohlcv":
        return parse_iso_z_ohlcv_line(line)
    if fmt == "epoch_ms_ohlc":
        return parse_epoch_ms_ohlc_line(line)
    raise ValueError(f"unsupported format: {fmt}")


def in_date_range(ts: datetime, start: date | None, end: date | None) -> bool:
    d = ts.date()
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


def load_free_ohlc_csv(
    path: Path,
    *,
    start: date | None = None,
    end: date | None = None,
    fmt: str | None = None,
) -> tuple[str, list[FreeOhlcBar]]:
    """Load and filter a free OHLC CSV. Returns (detected_format, bars)."""
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    detected = fmt or detect_format(raw_lines[:20])
    bars: list[FreeOhlcBar] = []
    for line in raw_lines:
        row = parse_line(line, detected)
        if row is None:
            continue
        if not in_date_range(row.timestamp, start, end):
            continue
        bars.append(row)
    return detected, bars


def locate_data_files(data_dir: Path, symbol: str) -> list[Path]:
    if not data_dir.is_dir():
        return []
    sym = normalize_symbol(symbol)
    patterns = [
        f"{sym}_1m.csv",
        f"{sym}_M1.csv",
        f"{sym}-M1.csv",
        f"{sym}*.csv",
        "*.csv",
    ]
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(data_dir.glob(pattern)):
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            if path.name.upper().startswith("README"):
                continue
            if path in seen:
                continue
            seen.add(path)
            found.append(path)
    return found
