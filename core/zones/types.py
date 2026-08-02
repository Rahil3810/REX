"""Zone-engine types and Strategy V1 HTF filters."""

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


@dataclass(frozen=True)
class ZoneDistance:
    """Distance from a price to a zone edge (never through the zone interior)."""

    zone: Zone
    distance_price: float
    distance_pips: float
    side: str  # "above" | "below" | "inside"
