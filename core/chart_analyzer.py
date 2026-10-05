"""Provide market context before strategies run."""

from core.logger import setup_logger
from core.market import distance_to_pips_for_symbol
from core.zones.types import select_preferred_inside_zone
from models.market_context import MarketContext, NearestZoneInfo
from models.zone import Zone, ZoneBook

logger = setup_logger("chart_analyzer")


class ChartAnalyzer:
    """
    Analyze current price against a ZoneBook to produce market context.

    Answers:
    - Current market price
    - Nearest zone above / below
    - Distance to each in pips
    - Whether price is inside a zone and which one
    - Zone strength and timeframe for the active zone

    Active-zone selection matches ``ZoneEngine`` / ``select_preferred_inside_zone``
    (strongest manual strength, then tightest range, then highest id).
    """

    def analyze(self, zone_book: ZoneBook, current_price: float) -> MarketContext:
        """Build a MarketContext snapshot for the given price and zone book."""
        symbol = zone_book.symbol
        active_zone = select_preferred_inside_zone(zone_book.zones, current_price)
        nearest_above = self._find_nearest_zone_above(
            zone_book.zones, current_price, symbol
        )
        nearest_below = self._find_nearest_zone_below(
            zone_book.zones, current_price, symbol
        )

        context = MarketContext(
            symbol=symbol,
            current_price=current_price,
            inside_zone=active_zone is not None,
            active_zone_id=active_zone.id if active_zone else None,
            active_zone_name=active_zone.name if active_zone else None,
            active_zone_strength=active_zone.strength if active_zone else None,
            active_zone_timeframe=active_zone.timeframe if active_zone else None,
            active_zone_source=(
                active_zone.source.value if active_zone is not None else None
            ),
            nearest_zone_above=nearest_above,
            nearest_zone_below=nearest_below,
        )
        logger.debug("Market context for %s: %s", symbol, context.to_dict())
        return context

    def _find_nearest_zone_above(
        self,
        zones: tuple[Zone, ...],
        current_price: float,
        symbol: str,
    ) -> NearestZoneInfo | None:
        """Return the nearest zone whose entire range is above current price."""
        candidates: list[NearestZoneInfo] = []

        for zone in zones:
            if zone.low > current_price:
                distance = distance_to_pips_for_symbol(
                    zone.low - current_price, symbol
                )
                candidates.append(
                    NearestZoneInfo(
                        id=zone.id,
                        distance_pips=distance,
                        name=zone.name,
                        timeframe=zone.timeframe,
                        strength=zone.strength,
                        source=zone.source.value,
                    )
                )

        if not candidates:
            return None
        return min(candidates, key=lambda info: info.distance_pips)

    def _find_nearest_zone_below(
        self,
        zones: tuple[Zone, ...],
        current_price: float,
        symbol: str,
    ) -> NearestZoneInfo | None:
        """Return the nearest zone whose entire range is below current price."""
        candidates: list[NearestZoneInfo] = []

        for zone in zones:
            if zone.high < current_price:
                distance = distance_to_pips_for_symbol(
                    current_price - zone.high, symbol
                )
                candidates.append(
                    NearestZoneInfo(
                        id=zone.id,
                        distance_pips=distance,
                        name=zone.name,
                        timeframe=zone.timeframe,
                        strength=zone.strength,
                        source=zone.source.value,
                    )
                )

        if not candidates:
            return None
        return min(candidates, key=lambda info: info.distance_pips)
