"""Zone-engine types and Strategy V1 HTF filters."""

from collections.abc import Sequence
from dataclasses import dataclass

from models.zone import Zone, ZoneKind

# Strategy V1 initially supports only these manually defined HTF roles.
SUPPORTED_HTF_TIMEFRAMES = frozenset({"daily", "weekly"})
SUPPORTED_HTF_KINDS = frozenset({ZoneKind.SUPPLY, ZoneKind.DEMAND})


def normalize_zone_timeframe(timeframe: str) -> str:
    """Map common aliases to canonical daily/weekly labels."""
    key = timeframe.strip().lower()
    aliases = {
        "d": "daily",
        "d1": "daily",
        "1d": "daily",
        "day": "daily",
        "daily": "daily",
        "w": "weekly",
        "w1": "weekly",
        "1w": "weekly",
        "week": "weekly",
        "weekly": "weekly",
    }
    return aliases.get(key, key)


def is_supported_htf_zone(zone: Zone) -> bool:
    """True when the zone is a Strategy V1 weekly/daily supply or demand zone."""
    if zone.kind not in SUPPORTED_HTF_KINDS:
        return False
    return normalize_zone_timeframe(zone.timeframe) in SUPPORTED_HTF_TIMEFRAMES


def select_preferred_inside_zone(
    zones: Sequence[Zone],
    price: float,
) -> Zone | None:
    """
    Canonical single-zone selection when price is inside one or more zones.

    Preference (stable, deterministic):
    1. highest ``strength`` (manual 0–10 rating — not confidence)
    2. tightest range ``-(high - low)``
    3. highest ``id`` as final tie-break
    """
    inside = [zone for zone in zones if zone.contains_price(price)]
    if not inside:
        return None
    return max(inside, key=lambda z: (z.strength, -(z.high - z.low), -z.id))


@dataclass(frozen=True)
class ZoneDistance:
    """Distance from a price to a zone edge (never through the zone interior)."""

    zone: Zone
    distance_price: float
    distance_pips: float
    side: str  # "above" | "below" | "inside"
