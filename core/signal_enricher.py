"""Enrich trading signals with market context from the chart analyzer."""

from models.market_context import MarketContext
from models.signal import Signal, SignalType
from models.zone import Zone, ZoneBook


def build_market_context_summary(
    signal_type: SignalType,
    zone: Zone,
    context: MarketContext,
) -> str:
    """Generate a human-readable summary combining signal and market context."""
    zone_label = f"{zone.timeframe} {zone.name}"

    if signal_type == SignalType.BREAK_ABOVE:
        base = f"Price broke above {zone_label}"
        if context.nearest_zone_above is not None:
            above = context.nearest_zone_above
            return (
                f"{base} and is approaching next {above.timeframe} zone "
                f"'{above.name}' ({above.distance_pips:.0f} pips away)."
            )
        return f"{base}."

    if signal_type == SignalType.BREAK_BELOW:
        base = f"Price broke below {zone_label}"
        if context.nearest_zone_below is not None:
            below = context.nearest_zone_below
            return (
                f"{base} and is approaching next {below.timeframe} zone "
                f"'{below.name}' ({below.distance_pips:.0f} pips away)."
            )
        return f"{base}."

    if signal_type == SignalType.ENTER_ZONE:
        return (
            f"Price entered {zone_label} "
            f"(strength {zone.strength})."
        )

    if signal_type == SignalType.CLOSE_OUTSIDE:
        if context.inside_zone:
            return f"Close outside {zone_label} while another zone is active."
        direction = "above" if context.current_price > zone.high else "below"
        return f"Close {direction} {zone_label}."

    return f"Signal {signal_type.value} on {zone_label}."


def enrich_signal(
    signal: Signal,
    context: MarketContext,
    zone_book: ZoneBook,
) -> Signal:
    """
    Add market context fields to a signal without modifying the original.

    Preserves all base signal fields; adds enrichment only when context is available.
    """
    zone = zone_book.get_zone(signal.zone_id)
    if zone is None:
        return signal

    nearest_above_id = (
        context.nearest_zone_above.id if context.nearest_zone_above else None
    )
    nearest_below_id = (
        context.nearest_zone_below.id if context.nearest_zone_below else None
    )
    distance_above = (
        context.nearest_zone_above.distance_pips
        if context.nearest_zone_above
        else None
    )
    distance_below = (
        context.nearest_zone_below.distance_pips
        if context.nearest_zone_below
        else None
    )

    return Signal(
        symbol=signal.symbol,
        signal=signal.signal,
        zone_id=signal.zone_id,
        price=signal.price,
        timestamp=signal.timestamp,
        reason=signal.reason,
        nearest_zone_above=nearest_above_id,
        nearest_zone_below=nearest_below_id,
        distance_to_zone_above=distance_above,
        distance_to_zone_below=distance_below,
        market_context_summary=build_market_context_summary(
            signal.signal, zone, context
        ),
    )
