"""Market context models produced by the chart analyzer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NearestZoneInfo:
    """Distance and identity of the nearest zone relative to current price."""

    id: int
    distance_pips: float
    name: str
    timeframe: str
    strength: int

    def to_dict(self) -> dict[str, str | float | int]:
        return {
            "id": self.id,
            "distance_pips": round(self.distance_pips, 1),
            "name": self.name,
            "timeframe": self.timeframe,
            "strength": self.strength,
        }


@dataclass(frozen=True)
class MarketContext:
    """Snapshot of price position relative to manually maintained zones."""

    symbol: str
    current_price: float
    inside_zone: bool
    active_zone_id: int | None
    active_zone_name: str | None
    active_zone_strength: int | None
    active_zone_timeframe: str | None
    nearest_zone_above: NearestZoneInfo | None
    nearest_zone_below: NearestZoneInfo | None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "inside_zone": self.inside_zone,
            "nearest_zone_above": (
                self.nearest_zone_above.to_dict() if self.nearest_zone_above else None
            ),
            "nearest_zone_below": (
                self.nearest_zone_below.to_dict() if self.nearest_zone_below else None
            ),
        }
        if self.inside_zone:
            payload["active_zone"] = {
                "id": self.active_zone_id,
                "name": self.active_zone_name,
                "strength": self.active_zone_strength,
                "timeframe": self.active_zone_timeframe,
            }
        return payload
