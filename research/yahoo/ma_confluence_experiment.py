"""Yahoo EURUSD H1 observational experiment for MA Confluence V1.

Runs the EXISTING locked MA Confluence V1 detector on Yahoo data.
Does not modify generator parameters, S002, or strategies.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from core.zones.auto.generated import GeneratedZone
from core.zones.auto.ma_confluence import (
    GENERATOR_VERSION,
    METHOD_MA_CONFLUENCE_ZONE_V1,
    MAConfluenceStatus,
    MAConfluenceZoneConfig,
    MAConfluenceZoneGenerator,
)
from models.bar import Bar
from research.ma_confluence_pipeline import candidate_export_row
from research.yahoo.adapter import (
    DATA_SOURCE,
    DEFAULT_SYMBOL,
    MIN_WARMUP_BARS,
    YAHOO_TICKER_EURUSD,
    YahooFetchResult,
    audit_yahoo_h1_bars,
    fetch_yahoo_h1,
    split_warmup_and_analysis,
    write_bars_csv,
)

EXPERIMENT_PIPELINE_VERSION = "yahoo_ma_confluence_obs_v1"
DEFAULT_DATA_DIR = Path("research/data/yahoo")
DEFAULT_OUTPUT_DIR = Path("research/outputs/ma_confluence")


@dataclass(frozen=True)
class YahooMAConfluenceExperimentResult:
    experiment_id: str
    analysis_days: int
    fetch: dict[str, Any]
    quality_audit: dict[str, Any]
    analysis_start: str
    analysis_end: str
    warmup_start: str
    warmup_bar_count: int
    analysis_bar_count: int
    total_bar_count: int
    config: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": EXPERIMENT_PIPELINE_VERSION,
            "experiment_id": self.experiment_id,
            "data_source": DATA_SOURCE,
            "ticker": YAHOO_TICKER_EURUSD,
            "method_id": METHOD_MA_CONFLUENCE_ZONE_V1,
            "generator_version": GENERATOR_VERSION,
            "analysis_days": self.analysis_days,
            "analysis_start": self.analysis_start,
            "analysis_end": self.analysis_end,
            "warmup_start": self.warmup_start,
            "warmup_bar_count": self.warmup_bar_count,
            "analysis_bar_count": self.analysis_bar_count,
            "bar_count": self.total_bar_count,
            "candidate_count": len(self.candidates),
            "config": self.config,
            "fetch": self.fetch,
            "quality_audit": self.quality_audit,
            "summary": self.summary,
            "candidates": list(self.candidates),
            "disclaimer": (
                "Observational Yahoo data-source experiment only. "
                "MA Confluence V1 parameters unchanged. "
                "S002 not executed. Do not retune on this output."
            ),
        }


def _price_at(bars: Sequence[Bar], index: int) -> float | None:
    if index < 0 or index >= len(bars):
        return None
    return float(bars[index].close)


def filter_candidates_to_analysis_window(
    generated: Sequence[GeneratedZone],
    *,
    analysis_start: datetime,
    analysis_end: datetime,
) -> tuple[GeneratedZone, ...]:
    """Keep zones whose creation time falls inside the analysis window."""
    return tuple(
        item
        for item in generated
        if analysis_start <= item.evidence.created_time <= analysis_end
    )


def summarize_candidates(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    widths = [float(r["high"]) - float(r["low"]) for r in rows]
    active = sum(1 for r in rows if r.get("status") == MAConfluenceStatus.ACTIVE.value)
    expired = sum(1 for r in rows if r.get("status") == MAConfluenceStatus.EXPIRED.value)
    return {
        "candidate_count": len(rows),
        "active_at_end": active,
        "expired": expired,
        "average_zone_width": None if not widths else statistics.mean(widths),
        "min_zone_width": None if not widths else min(widths),
        "max_zone_width": None if not widths else max(widths),
    }


def run_yahoo_ma_confluence_experiment(
    *,
    analysis_days: int,
    experiment_id: str,
    config: MAConfluenceZoneConfig | None = None,
    min_warmup_bars: int = MIN_WARMUP_BARS,
    fetch_lookback_days: int | None = None,
    bars: Sequence[Bar] | None = None,
    fetch_meta: YahooFetchResult | None = None,
    data_csv_path: Path | None = None,
) -> YahooMAConfluenceExperimentResult:
    """Run locked MA Confluence V1 on Yahoo H1 with causal warmup.

    If ``bars`` is provided (tests), network fetch is skipped.
    """
    cfg = config or MAConfluenceZoneConfig()

    lookback = fetch_lookback_days
    if lookback is None:
        # ~300 H1 bars ≈ several FX weeks; pad generously for weekends/gaps.
        lookback = max(60, analysis_days + 45)

    if bars is None:
        fetch = fetch_yahoo_h1(
            ticker=YAHOO_TICKER_EURUSD,
            symbol=DEFAULT_SYMBOL,
            period_days=lookback,
            skip_invalid_ohlc=True,
        )
        all_bars = fetch.bars
        fetch_dict = fetch.to_dict()
        filter_notes = fetch.notes
        source_tz = fetch.source_timezone
    else:
        all_bars = tuple(bars)
        fetch = fetch_meta
        fetch_dict = (
            fetch.to_dict()
            if fetch is not None
            else {
                "data_source": DATA_SOURCE,
                "ticker": YAHOO_TICKER_EURUSD,
                "note": "bars injected (no network fetch)",
            }
        )
        filter_notes = ()
        source_tz = "injected"

    warmup, analysis, analysis_start, analysis_end = split_warmup_and_analysis(
        all_bars,
        analysis_days=analysis_days,
        min_warmup_bars=min_warmup_bars,
    )
    combined = warmup + analysis
    warmup_start = warmup[0].timestamp

    if data_csv_path is not None:
        write_bars_csv(combined, data_csv_path)

    audit = audit_yahoo_h1_bars(
        combined,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        warmup_start=warmup_start,
        timezone_label=f"UTC_naive (source={source_tz})",
        filter_reasons=filter_notes,
    )

    generator = MAConfluenceZoneGenerator(config=cfg)
    generated = generator.generate(
        combined,
        timeframe="H1",
        asof_index=len(combined) - 1,
        asof_time=combined[-1].timestamp,
    )
    windowed = filter_candidates_to_analysis_window(
        generated,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    rows = tuple(
        {
            **candidate_export_row(
                item,
                price_at_creation=_price_at(combined, item.evidence.created_index),
            ),
            "source": DATA_SOURCE,
            "generator_version": item.evidence.generator_version,
            "separation_atr": item.evidence.separation_over_atr,
        }
        for item in windowed
    )
    summary = summarize_candidates(rows)
    return YahooMAConfluenceExperimentResult(
        experiment_id=experiment_id,
        analysis_days=analysis_days,
        fetch=fetch_dict,
        quality_audit=audit.to_dict(),
        analysis_start=analysis_start.isoformat(sep=" "),
        analysis_end=analysis_end.isoformat(sep=" "),
        warmup_start=warmup_start.isoformat(sep=" "),
        warmup_bar_count=len(warmup),
        analysis_bar_count=len(analysis),
        total_bar_count=len(combined),
        config=cfg.to_dict(),
        candidates=rows,
        summary=summary,
    )


def write_experiment_json(
    result: YahooMAConfluenceExperimentResult, path: Path
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def format_experiment_summary(result: YahooMAConfluenceExperimentResult) -> str:
    s = result.summary
    lines = [
        "=== YAHOO EURUSD MA CONFLUENCE ===",
        "",
        f"Experiment: {result.experiment_id}",
        "",
        "Analysis:",
        f"Start: {result.analysis_start}",
        f"End: {result.analysis_end}",
        f"H1 bars: {result.analysis_bar_count}",
        f"Warm-up bars: {result.warmup_bar_count}",
        "",
        "Candidates:",
        f"Total: {s['candidate_count']}",
        f"Active at end: {s['active_at_end']}",
        f"Expired: {s['expired']}",
        f"Average zone width: {s['average_zone_width']}",
        f"Min zone width: {s['min_zone_width']}",
        f"Max zone width: {s['max_zone_width']}",
        "",
    ]
    for i, row in enumerate(result.candidates, start=1):
        width = float(row["high"]) - float(row["low"])
        lines.extend(
            [
                f"Zone #{i}",
                f"ID: {row['zone_id']}",
                f"Created: {row['created_at']}",
                f"Low: {row['low']}",
                f"High: {row['high']}",
                f"Width: {width}",
                f"EMA20: {row['EMA20']}",
                f"EMA50: {row['EMA50']}",
                f"EMA200: {row['EMA200']}",
                f"ATR14: {row['ATR14']}",
                f"Separation: {row['separation']}",
                f"Sep/ATR: {row.get('separation_atr', row.get('separation_over_atr'))}",
                f"Convergence duration: {row['convergence_duration']}",
                f"Expired: {row['expired_at']}",
                f"Distance from price: {row['distance_from_price']}",
                "",
            ]
        )
    if not result.candidates:
        lines.append("(no candidates in analysis window)")
        lines.append("")
    return "\n".join(lines)


def run_both_yahoo_experiments(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    min_warmup_bars: int = MIN_WARMUP_BARS,
) -> tuple[YahooMAConfluenceExperimentResult, YahooMAConfluenceExperimentResult]:
    """Fetch once (long lookback), run 7D and 1M observational experiments."""
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Shared fetch: enough for 30d analysis + 300 H1 warmup.
    fetch = fetch_yahoo_h1(
        ticker=YAHOO_TICKER_EURUSD,
        symbol=DEFAULT_SYMBOL,
        period_days=120,
        skip_invalid_ohlc=True,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    csv_path = data_dir / f"EURUSD_H1_{stamp}.csv"
    write_bars_csv(fetch.bars, csv_path)
    # Stable aliases for research convenience.
    write_bars_csv(fetch.bars, data_dir / "EURUSD_H1_latest.csv")
    write_bars_csv(fetch.bars, data_dir / "EURUSD_H1_2026.csv")

    result_7d = run_yahoo_ma_confluence_experiment(
        analysis_days=7,
        experiment_id="7D",
        min_warmup_bars=min_warmup_bars,
        bars=fetch.bars,
        fetch_meta=fetch,
    )
    result_1m = run_yahoo_ma_confluence_experiment(
        analysis_days=30,
        experiment_id="1M",
        min_warmup_bars=min_warmup_bars,
        bars=fetch.bars,
        fetch_meta=fetch,
    )
    write_experiment_json(result_7d, output_dir / "yahoo_eurusd_7d.json")
    write_experiment_json(result_1m, output_dir / "yahoo_eurusd_1m.json")
    return result_7d, result_1m
