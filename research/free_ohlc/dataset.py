"""Research dataset builder: free OHLC → canonical Bars → HTF set."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from models.bar import Bar
from research.free_ohlc.adapter import AdapterResult, AdapterStats, load_free_ohlc
from research.free_ohlc.resampler import (
    RESAMPLER_VERSION,
    SUPPORTED_TIMEFRAMES,
    ResampleResult,
    resample_bars,
)

DATASET_VERSION = "free_ohlc_research_dataset_v1"


@dataclass(frozen=True)
class ResearchDataset:
    """Multi-timeframe research bars derived from one free OHLC source."""

    symbol: str
    source_timeframe: str
    frames: dict[str, tuple[Bar, ...]]
    adapter: AdapterResult
    resamples: dict[str, ResampleResult]
    provenance: dict[str, object] = field(default_factory=dict)

    def bars(self, timeframe: str) -> tuple[Bar, ...]:
        tf = timeframe.strip().upper()
        if tf not in self.frames:
            raise KeyError(tf)
        return self.frames[tf]


def build_research_dataset(
    path: Path | str,
    *,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    source_timeframe: str = "M1",
    skip_invalid_ohlc: bool = False,
    target_timeframes: tuple[str, ...] = SUPPORTED_TIMEFRAMES,
    allow_partial: bool = False,
) -> ResearchDataset:
    """Load free OHLC M1 and deterministically resample to target frames."""
    adapter = load_free_ohlc(
        path,
        symbol=symbol,
        timeframe=source_timeframe,
        start=start,
        end=end,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )
    volume_type = adapter.stats.volume_type
    resamples: dict[str, ResampleResult] = {}
    frames: dict[str, tuple[Bar, ...]] = {}

    for tf in target_timeframes:
        key = tf.strip().upper()
        result = resample_bars(
            adapter.bars,
            target_timeframe=key,
            volume_type=volume_type if volume_type != "none" else "none",
            allow_partial=allow_partial,
        )
        resamples[key] = result
        frames[key] = result.bars

    provenance = {
        "dataset_version": DATASET_VERSION,
        "resampler_version": RESAMPLER_VERSION,
        "source": adapter.provenance.get("source"),
        "source_path": adapter.provenance.get("source_path"),
        "symbol": adapter.provenance.get("symbol"),
        "source_timeframe": source_timeframe.strip().upper(),
        "timestamp_policy": adapter.stats.timezone_policy,
        "volume_type": volume_type,
        "invalid_row_policy": adapter.provenance.get("invalid_row_policy"),
        "allow_partial": allow_partial,
        "target_timeframes": [t.strip().upper() for t in target_timeframes],
        "requested_start": start.isoformat() if start else None,
        "requested_end": end.isoformat() if end else None,
    }
    return ResearchDataset(
        symbol=adapter.provenance["symbol"],  # type: ignore[arg-type]
        source_timeframe=source_timeframe.strip().upper(),
        frames=frames,
        adapter=adapter,
        resamples=resamples,
        provenance=provenance,
    )


def adapter_stats_to_dict(stats: AdapterStats) -> dict[str, object]:
    return {
        "rows_read": stats.rows_read,
        "rows_accepted": stats.rows_accepted,
        "rows_dropped_invalid": stats.rows_dropped_invalid,
        "rows_dropped_date_filter": stats.rows_dropped_date_filter,
        "parse_error_count": stats.parse_error_count,
        "invalid_ohlc_count": stats.invalid_ohlc_count,
        "duplicate_timestamp_count": stats.duplicate_timestamp_count,
        "out_of_order_count": stats.out_of_order_count,
        "first_timestamp": (
            stats.first_timestamp.isoformat(sep=" ") if stats.first_timestamp else None
        ),
        "last_timestamp": (
            stats.last_timestamp.isoformat(sep=" ") if stats.last_timestamp else None
        ),
        "bar_count": stats.bar_count,
        "volume_type": stats.volume_type,
        "timezone_policy": stats.timezone_policy,
        "source_format": stats.source_format,
        "skip_invalid_ohlc": stats.skip_invalid_ohlc,
    }
