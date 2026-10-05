"""CLI: Automatic Zone V1 geometry construction audit (research-only)."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from research.zone_geometry_audit import run_zone_geometry_audit

REPORT_PATH = Path("/tmp/rex_zone_geometry_audit.json")
DEFAULT_CSV = Path("research/data/free_ohlc/EURUSD/M1/EURUSD_1m.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="REX Zone V1 geometry audit — trace boundary construction"
    )
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default=None, help="YYYY-MM-DD (default: dataset bounds)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (default: dataset bounds)")
    p.add_argument("--timeframe", default="M15")
    p.add_argument("--report", type=Path, default=REPORT_PATH)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    result = run_zone_geometry_audit(
        args.csv,
        symbol=args.symbol,
        start=start,
        end=end,
        timeframe=args.timeframe,
    )
    payload = result.to_dict()
    args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    fw = result.full_window
    dist = fw.get("distributions", {})
    w_atr = dist.get("width_over_atr_origin", {})
    geo = fw.get("geometry_type_counts", {})
    bv = fw.get("boundary_verification", {})

    print("=== REX ZONE V1 GEOMETRY AUDIT ===")
    print(f"source: {result.source_path}")
    print(f"window: {result.effective_start} .. {result.effective_end}")
    print(f"zones: {fw.get('zone_count')}")
    print(
        f"geometry: single={geo.get('single_swing_expanded')} "
        f"multi={geo.get('multi_swing_envelope')}"
    )
    print(
        f"boundary verification: matches={bv.get('matches')} "
        f"mismatches={bv.get('mismatches')}"
    )
    print(f"median width/ATR (origin): {w_atr.get('median')}")
    print(f"median width: {dist.get('absolute_width', {}).get('median')}")
    print(f"median swing spread/ATR: {dist.get('swing_spread_over_atr_origin', {}).get('median')}")
    print("--- THIRDS ---")
    for row in result.chronological_thirds:
        rd = row.get("distributions", {}).get("width_over_atr_origin", {})
        print(
            f"{row['label']}: zones={row.get('zone_count')} "
            f"median_w/atr={rd.get('median')} "
            f"multi_pct={row.get('geometry_type_pct', {}).get('multi_swing_envelope')}"
        )
    print(f"conclusion: {result.conclusion['answer'][:120]}...")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
