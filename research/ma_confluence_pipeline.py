"""Research pipeline: free OHLC → HTF → MA Confluence Zone V1 → export.

Does not modify strategies, BacktestRunner, or live trading paths.
First validation experiment: EURUSD H1 with frozen V1 config.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from core.zones.auto.generated import GeneratedZone
from core.zones.auto.ma_confluence import (
    METHOD_MA_CONFLUENCE_ZONE_V1,
    MAConfluenceEvidence,
    MAConfluenceZoneConfig,
    MAConfluenceZoneGenerator,
)
from models.bar import Bar
from models.zone import ZoneBook
from research.free_ohlc.dataset import build_research_dataset
from research.zones_pipeline import resolve_evaluation_window

PIPELINE_VERSION = "ma_confluence_candidates_v1"
DEFAULT_TIMEFRAME = "H1"
DEFAULT_SYMBOL = "EURUSD"


@dataclass(frozen=True)
class MAConfluencePipelineResult:
    pipeline_version: str
    source_path: str
    symbol: str
    timeframe: str
    effective_start: str | None
    effective_end: str | None
    config: dict[str, Any]
    bar_count: int
    candidates: tuple[GeneratedZone, ...]
    export_rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "method_id": METHOD_MA_CONFLUENCE_ZONE_V1,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "effective_start": self.effective_start,
            "effective_end": self.effective_end,
            "config": self.config,
            "bar_count": self.bar_count,
            "candidate_count": len(self.candidates),
            "candidates": [row for row in self.export_rows],
            "research_questions": {
                "A": (
                    "Are automatically generated MA zones visually/"
                    "structurally meaningful? (manual labels)"
                ),
                "B": (
                    "Do S002 breakout→retest setups around those zones have "
                    "measurable edge? (deferred historical evaluation)"
                ),
                "note": (
                    "A good VALID rate does not prove S002 profitability. "
                    "Do not retune config on this frozen validation sample."
                ),
            },
            "disclaimer": (
                "Causal research candidates only. Frozen snapshots. "
                "EMA200 is evidence-only."
            ),
        }


def candidate_export_row(
    generated: GeneratedZone,
    *,
    price_at_creation: float | None,
) -> dict[str, Any]:
    """Flatten a GeneratedZone into the manual-review export schema."""
    zone = generated.zone
    ev: MAConfluenceEvidence = generated.evidence
    mid = (zone.low + zone.high) / 2.0
    if price_at_creation is None:
        distance = None
    else:
        if price_at_creation < zone.low:
            distance = zone.low - price_at_creation
        elif price_at_creation > zone.high:
            distance = price_at_creation - zone.high
        else:
            distance = 0.0

    chart_hint = (
        f"{ev.symbol} {ev.timeframe} @ {ev.created_time.isoformat(sep=' ')} "
        f"mid={mid:.5f}"
    )
    return {
        "zone_id": zone.id,
        "symbol": ev.symbol,
        "timeframe": ev.timeframe,
        "created_at": ev.created_time.isoformat(sep=" "),
        "low": zone.low,
        "high": zone.high,
        "EMA20": ev.ema20,
        "EMA50": ev.ema50,
        "EMA200": ev.ema200,
        "ATR14": ev.atr14,
        "separation": ev.separation,
        "separation_over_atr": ev.separation_over_atr,
        "convergence_start": ev.convergence_start_time.isoformat(sep=" "),
        "convergence_duration": ev.convergence_duration_bars,
        "status": ev.status.value,
        "expired_at": (
            None
            if ev.expired_time is None
            else ev.expired_time.isoformat(sep=" ")
        ),
        "distance_from_price": distance,
        "chart_hint": chart_hint,
        "generator_version": ev.generator_version,
        "created_index": ev.created_index,
        "convergence_start_index": ev.convergence_start_index,
    }


def generated_zones_to_zone_book(
    symbol: str,
    generated: Sequence[GeneratedZone],
) -> ZoneBook:
    """Adapter for later S002 injection (Phase 7) — unused in Phases 1–3."""
    return ZoneBook(
        symbol=symbol,
        zones=tuple(item.zone for item in generated),
    )


def run_ma_confluence_pipeline(
    csv_path: Path | str,
    *,
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    start: date | None = None,
    end: date | None = None,
    config: MAConfluenceZoneConfig | None = None,
    skip_invalid_ohlc: bool = True,
    allow_partial: bool = False,
    asof_index: int | None = None,
) -> MAConfluencePipelineResult:
    """Generate MA confluence candidates on one HTF series."""
    cfg = config or MAConfluenceZoneConfig()
    path = Path(csv_path)
    bounds, eff_start, eff_end = resolve_evaluation_window(
        path,
        symbol=symbol,
        start=start,
        end=end,
        skip_invalid_ohlc=skip_invalid_ohlc,
    )
    _ = bounds
    dataset = build_research_dataset(
        path,
        symbol=symbol,
        start=eff_start,
        end=eff_end,
        source_timeframe="M1",
        skip_invalid_ohlc=skip_invalid_ohlc,
        target_timeframes=(timeframe,),
        allow_partial=allow_partial,
    )
    bars = dataset.bars(timeframe)
    if not bars:
        return MAConfluencePipelineResult(
            pipeline_version=PIPELINE_VERSION,
            source_path=str(path),
            symbol=symbol.upper(),
            timeframe=timeframe,
            effective_start=None if eff_start is None else eff_start.isoformat(),
            effective_end=None if eff_end is None else eff_end.isoformat(),
            config=cfg.to_dict(),
            bar_count=0,
            candidates=(),
            export_rows=(),
        )

    resolved_asof = len(bars) - 1 if asof_index is None else asof_index
    generator = MAConfluenceZoneGenerator(config=cfg)
    candidates = generator.generate(
        bars,
        timeframe=timeframe,
        asof_index=resolved_asof,
        asof_time=bars[resolved_asof].timestamp,
    )
    rows = tuple(
        candidate_export_row(
            item,
            price_at_creation=_price_at(bars, item.evidence.created_index),
        )
        for item in candidates
    )
    return MAConfluencePipelineResult(
        pipeline_version=PIPELINE_VERSION,
        source_path=str(path),
        symbol=symbol.upper(),
        timeframe=timeframe,
        effective_start=None if eff_start is None else eff_start.isoformat(),
        effective_end=None if eff_end is None else eff_end.isoformat(),
        config=cfg.to_dict(),
        bar_count=len(bars),
        candidates=candidates,
        export_rows=rows,
    )


def write_candidates_json(result: MAConfluencePipelineResult, path: Path) -> None:
    path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def write_candidates_csv(result: MAConfluencePipelineResult, path: Path) -> None:
    fieldnames = [
        "zone_id",
        "symbol",
        "timeframe",
        "created_at",
        "low",
        "high",
        "EMA20",
        "EMA50",
        "EMA200",
        "ATR14",
        "separation",
        "separation_over_atr",
        "convergence_start",
        "convergence_duration",
        "status",
        "expired_at",
        "distance_from_price",
        "chart_hint",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in result.export_rows:
            writer.writerow(row)


def _price_at(bars: Sequence[Bar], index: int) -> float | None:
    if index < 0 or index >= len(bars):
        return None
    return float(bars[index].close)
