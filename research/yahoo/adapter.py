"""Yahoo Finance research data adapter (thin, research-only).

Fetches EURUSD=X H1 via yfinance, normalizes timestamps to naive UTC,
and builds canonical REX ``Bar`` objects for existing generators.

Does not modify MA Confluence V1 or any strategy code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from historical.bar_contract import build_canonical_bar, validate_ohlc
from historical.exceptions import HistoricalParseError
from models.bar import Bar

YAHOO_TICKER_EURUSD = "EURUSD=X"
DATA_SOURCE = "yahoo"
DEFAULT_SYMBOL = "EURUSD"
DEFAULT_INTERVAL = "1h"
MIN_WARMUP_BARS = 300


@dataclass(frozen=True)
class YahooFetchResult:
    """Raw Yahoo download converted to canonical REX bars."""

    ticker: str
    symbol: str
    interval: str
    bars: tuple[Bar, ...]
    source_timezone: str
    fetched_at_utc: datetime
    yfinance_version: str | None
    row_count_raw: int
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_source": DATA_SOURCE,
            "ticker": self.ticker,
            "symbol": self.symbol,
            "interval": self.interval,
            "source_timezone": self.source_timezone,
            "fetched_at_utc": self.fetched_at_utc.isoformat(sep=" "),
            "yfinance_version": self.yfinance_version,
            "row_count_raw": self.row_count_raw,
            "bar_count": len(self.bars),
            "first_timestamp": (
                None if not self.bars else self.bars[0].timestamp.isoformat(sep=" ")
            ),
            "last_timestamp": (
                None if not self.bars else self.bars[-1].timestamp.isoformat(sep=" ")
            ),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class YahooH1QualityAudit:
    """Lightweight data-quality report for Yahoo H1 bars."""

    total_h1_rows: int
    analysis_start: datetime | None
    analysis_end: datetime | None
    warmup_start: datetime | None
    timezone: str
    duplicate_timestamps: int
    missing_h1_buckets: int
    invalid_ohlc_candles: int
    flat_candles: int
    zero_volume_candles: int
    weekend_candles: int
    chronological: bool
    ohlc_continuity_gaps: int
    filtered_count: int
    filter_reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_h1_rows": self.total_h1_rows,
            "analysis_start": _iso(self.analysis_start),
            "analysis_end": _iso(self.analysis_end),
            "warmup_start": _iso(self.warmup_start),
            "timezone": self.timezone,
            "duplicate_timestamps": self.duplicate_timestamps,
            "missing_h1_buckets": self.missing_h1_buckets,
            "invalid_ohlc_candles": self.invalid_ohlc_candles,
            "flat_candles": self.flat_candles,
            "zero_volume_candles": self.zero_volume_candles,
            "weekend_candles": self.weekend_candles,
            "chronological": self.chronological,
            "ohlc_continuity_gaps": self.ohlc_continuity_gaps,
            "filtered_count": self.filtered_count,
            "filter_reasons": list(self.filter_reasons),
            "details": self.details,
        }


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(sep=" ")


def _flatten_yahoo_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = [str(col[0]) for col in frame.columns]
    return frame


def normalize_yahoo_timestamp(ts: Any) -> datetime:
    """Convert Yahoo index timestamp to naive UTC wall time."""
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            # Treat naive Yahoo stamps as UTC (unusual for H1 EURUSD=X).
            return ts.to_pydatetime().replace(tzinfo=None)
        return ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    raise TypeError(f"unsupported timestamp type: {type(ts)!r}")


def dataframe_to_bars(
    frame: pd.DataFrame,
    *,
    symbol: str = DEFAULT_SYMBOL,
    skip_invalid_ohlc: bool = False,
) -> tuple[tuple[Bar, ...], tuple[str, ...]]:
    """Map a Yahoo OHLCV frame to canonical REX bars.

    Invalid OHLC rows are skipped only when ``skip_invalid_ohlc=True``;
    otherwise they raise. Filtering is never silent — reasons are returned.
    """
    if frame.empty:
        return (), ()

    frame = _flatten_yahoo_columns(frame)
    required = {"Open", "High", "Low", "Close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Yahoo frame missing columns: {sorted(missing)}")

    bars: list[Bar] = []
    notes: list[str] = []
    for ts, row in frame.iterrows():
        try:
            vol = row["Volume"] if "Volume" in frame.columns else None
            if vol is not None and pd.isna(vol):
                vol = None
            bar = build_canonical_bar(
                symbol=symbol,
                timestamp=normalize_yahoo_timestamp(ts),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=None if vol is None else float(vol),
            )
        except (HistoricalParseError, TypeError, ValueError) as exc:
            msg = f"skip/invalid at {ts!r}: {exc}"
            if skip_invalid_ohlc:
                notes.append(msg)
                continue
            raise HistoricalParseError(msg) from exc
        bars.append(bar)

    bars.sort(key=lambda b: b.timestamp)
    # Drop exact duplicate timestamps (keep first).
    deduped: list[Bar] = []
    seen: set[datetime] = set()
    for bar in bars:
        if bar.timestamp in seen:
            notes.append(f"duplicate timestamp dropped: {bar.timestamp.isoformat()}")
            continue
        seen.add(bar.timestamp)
        deduped.append(bar)
    return tuple(deduped), tuple(notes)


def fetch_yahoo_h1(
    *,
    ticker: str = YAHOO_TICKER_EURUSD,
    symbol: str = DEFAULT_SYMBOL,
    start: datetime | None = None,
    end: datetime | None = None,
    period_days: int | None = None,
    skip_invalid_ohlc: bool = True,
) -> YahooFetchResult:
    """Download Yahoo H1 OHLCV and convert to canonical bars."""
    import yfinance as yf

    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    end_dt = end or datetime.now(timezone.utc)
    if end_dt.tzinfo is not None:
        end_dt = end_dt.astimezone(timezone.utc)
    else:
        end_dt = end_dt.replace(tzinfo=timezone.utc)

    if start is not None:
        start_dt = start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)
        start_dt = start_dt.astimezone(timezone.utc)
    elif period_days is not None:
        start_dt = end_dt - timedelta(days=period_days)
    else:
        start_dt = end_dt - timedelta(days=90)

    raw = yf.download(
        ticker,
        start=start_dt.date().isoformat(),
        end=(end_dt + timedelta(days=1)).date().isoformat(),
        interval=DEFAULT_INTERVAL,
        auto_adjust=False,
        progress=False,
    )
    source_tz = "unknown"
    if not raw.empty and getattr(raw.index, "tz", None) is not None:
        source_tz = str(raw.index.tz)

    bars, notes = dataframe_to_bars(
        raw, symbol=symbol, skip_invalid_ohlc=skip_invalid_ohlc
    )
    version = getattr(yf, "__version__", None)
    return YahooFetchResult(
        ticker=ticker,
        symbol=symbol.upper(),
        interval=DEFAULT_INTERVAL,
        bars=bars,
        source_timezone=source_tz,
        fetched_at_utc=fetched_at,
        yfinance_version=None if version is None else str(version),
        row_count_raw=int(len(raw)),
        notes=notes,
    )


def write_bars_csv(bars: Sequence[Bar], path: Path) -> None:
    """Persist canonical bars as a simple research CSV (UTC naive timestamps)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,open,high,low,close,volume"]
    for bar in bars:
        vol = "" if bar.volume is None else str(bar.volume)
        lines.append(
            f"{bar.timestamp.isoformat(sep=' ')},"
            f"{bar.open},{bar.high},{bar.low},{bar.close},{vol}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_yahoo_h1_bars(
    bars: Sequence[Bar],
    *,
    analysis_start: datetime | None = None,
    analysis_end: datetime | None = None,
    warmup_start: datetime | None = None,
    timezone_label: str = "UTC_naive_from_Yahoo",
    filter_reasons: Sequence[str] = (),
) -> YahooH1QualityAudit:
    """Audit H1 bars without mutating them."""
    timestamps = [b.timestamp for b in bars]
    duplicate_timestamps = len(timestamps) - len(set(timestamps))
    chronological = all(
        timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1)
    )

    invalid = 0
    flat = 0
    zero_vol = 0
    weekend = 0
    for bar in bars:
        try:
            validate_ohlc(bar.open, bar.high, bar.low, bar.close)
        except HistoricalParseError:
            invalid += 1
        if bar.high == bar.low == bar.open == bar.close:
            flat += 1
        if bar.volume is not None and bar.volume == 0.0:
            zero_vol += 1
        if bar.timestamp.weekday() >= 5:
            weekend += 1

    missing = 0
    continuity_gaps = 0
    if len(bars) >= 2:
        for i in range(len(bars) - 1):
            delta = bars[i + 1].timestamp - bars[i].timestamp
            hours = delta.total_seconds() / 3600.0
            if hours > 1.0 + 1e-9:
                # Count skipped hourly slots excluding obvious weekend gaps.
                gap_hours = int(hours) - 1
                missing += max(0, gap_hours)
                continuity_gaps += 1

    return YahooH1QualityAudit(
        total_h1_rows=len(bars),
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        warmup_start=warmup_start,
        timezone=timezone_label,
        duplicate_timestamps=duplicate_timestamps,
        missing_h1_buckets=missing,
        invalid_ohlc_candles=invalid,
        flat_candles=flat,
        zero_volume_candles=zero_vol,
        weekend_candles=weekend,
        chronological=chronological,
        ohlc_continuity_gaps=continuity_gaps,
        filtered_count=len(filter_reasons),
        filter_reasons=tuple(filter_reasons),
        details={
            "first_bar": _iso(bars[0].timestamp) if bars else None,
            "last_bar": _iso(bars[-1].timestamp) if bars else None,
        },
    )


def split_warmup_and_analysis(
    bars: Sequence[Bar],
    *,
    analysis_days: int,
    min_warmup_bars: int = MIN_WARMUP_BARS,
) -> tuple[tuple[Bar, ...], tuple[Bar, ...], datetime, datetime]:
    """Split downloaded bars into warmup + analysis using the latest complete window.

    Analysis end = last bar timestamp.
    Analysis start = first bar with timestamp >= (analysis_end - analysis_days).
    Warmup = all bars strictly before analysis start.
    """
    if not bars:
        raise ValueError("no bars available for warmup/analysis split")
    if analysis_days < 1:
        raise ValueError("analysis_days must be >= 1")

    analysis_end = bars[-1].timestamp
    cutoff = analysis_end - timedelta(days=analysis_days)
    analysis = tuple(b for b in bars if b.timestamp >= cutoff)
    if not analysis:
        raise ValueError("analysis window is empty")
    analysis_start = analysis[0].timestamp
    warmup = tuple(b for b in bars if b.timestamp < analysis_start)
    if len(warmup) < min_warmup_bars:
        raise ValueError(
            f"insufficient warmup bars: have {len(warmup)}, need >= {min_warmup_bars}. "
            "Fetch a longer Yahoo history."
        )
    return warmup, analysis, analysis_start, analysis_end
