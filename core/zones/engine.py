"""Query engine over manually (or otherwise) provided zones."""

from core.market import distance_to_pips_for_symbol
from core.zones.providers import ZoneProvider
from core.zones.types import ZoneDistance, is_supported_htf_zone
from models.zone import Zone, ZoneKind


class ZoneEngine:
    """
    Answers zone questions for research and Strategy V1 consumers.

    Does not detect zones. Detection/source belongs in a ``ZoneProvider``.
    By default, HTF helpers restrict to weekly/daily supply and demand.
    """

    def __init__(self, provider: ZoneProvider) -> None:
        self._provider = provider

    @property
    def provider(self) -> ZoneProvider:
        return self._provider

    def zones(
        self,
        symbol: str,
        *,
        htf_only: bool = False,
        kind: ZoneKind | None = None,
    ) -> tuple[Zone, ...]:
        """Return zones for a symbol, optionally filtered to Strategy V1 HTF set."""
        zones = self._provider.zones_for(symbol)
        if htf_only:
            zones = tuple(z for z in zones if is_supported_htf_zone(z))
        if kind is not None:
            zones = tuple(z for z in zones if z.kind is kind)
        return zones

    def is_price_inside_zone(
        self,
        symbol: str,
        price: float,
        *,
        htf_only: bool = True,
    ) -> bool:
        """Return True when price sits inside at least one selected zone."""
        return bool(self.active_zones(symbol, price, htf_only=htf_only))

    def active_zones(
        self,
        symbol: str,
        price: float,
        *,
        htf_only: bool = True,
    ) -> tuple[Zone, ...]:
        """Return every selected zone that contains ``price``."""
        return tuple(
            zone
            for zone in self.zones(symbol, htf_only=htf_only)
            if zone.contains_price(price)
        )

    def distance_to_nearest_zone(
        self,
        symbol: str,
        price: float,
        *,
        htf_only: bool = True,
    ) -> ZoneDistance | None:
        """
        Distance to the nearest selected zone.

        Inside a zone: distance is 0 with ``side="inside"``.
        Otherwise: distance to the closest edge among zones fully above or below.
        """
        zones = self.zones(symbol, htf_only=htf_only)
        if not zones:
            return None

        inside = [zone for zone in zones if zone.contains_price(price)]
        if inside:
            # Prefer strongest, then tightest range for a stable pick.
            zone = max(inside, key=lambda z: (z.strength, -(z.high - z.low), -z.id))
            return ZoneDistance(
                zone=zone,
                distance_price=0.0,
                distance_pips=0.0,
                side="inside",
            )

        candidates: list[ZoneDistance] = []
        for zone in zones:
            if zone.low > price:
                gap = zone.low - price
                candidates.append(
                    ZoneDistance(
                        zone=zone,
                        distance_price=gap,
                        distance_pips=distance_to_pips_for_symbol(gap, symbol),
                        side="above",
                    )
                )
            elif zone.high < price:
                gap = price - zone.high
                candidates.append(
                    ZoneDistance(
                        zone=zone,
                        distance_price=gap,
                        distance_pips=distance_to_pips_for_symbol(gap, symbol),
                        side="below",
                    )
                )

        if not candidates:
            return None
        return min(candidates, key=lambda item: (item.distance_price, -item.zone.strength))
