"""REX Fill Models implementing execution pricing assumptions."""

from typing import Protocol

from models.bar import Bar
from models.entry_model import EntryModel
from models.position import Position
from models.trade_direction import TradeDirection
from models.trade_plan import TradePlan


class FillModel(Protocol):
    """Protocol for execution-price and OHLC fill assumptions."""

    def check_entry(self, plan: TradePlan, bar: Bar) -> float | None:
        """
        Determine entry fill price from current OHLC bar.

        Returns actual fill price if triggered, otherwise None.
        """
        ...

    def check_exit(self, position: Position, bar: Bar) -> tuple[float, str] | None:
        """
        Determine SL/TP exit price and reason from current OHLC bar.

        Returns (actual_exit_price, close_reason) if hit, otherwise None.
        """
        ...


class ConservativeOHLCFillModel:
    """V1 default fill model implementing conservative OHLC execution assumptions."""

    def check_entry(self, plan: TradePlan, bar: Bar) -> float | None:
        if plan.entry_model == EntryModel.NEXT_CANDLE_OPEN:
            return bar.open
        return None

    def check_exit(self, position: Position, bar: Bar) -> tuple[float, str] | None:
        hit_sl = False
        hit_tp = False

        if position.direction == TradeDirection.LONG:
            if bar.low <= position.sl_price:
                hit_sl = True
            if bar.high >= position.tp_price:
                hit_tp = True
        else:
            if bar.high >= position.sl_price:
                hit_sl = True
            if bar.low <= position.tp_price:
                hit_tp = True

        if hit_sl and hit_tp:
            if (
                position.direction == TradeDirection.LONG
                and bar.open <= position.sl_price
            ):
                return bar.open, "AMBIGUITY"
            if (
                position.direction == TradeDirection.SHORT
                and bar.open >= position.sl_price
            ):
                return bar.open, "AMBIGUITY"
            return position.sl_price, "AMBIGUITY"

        if hit_sl:
            if (
                position.direction == TradeDirection.LONG
                and bar.open <= position.sl_price
            ):
                return bar.open, "SL"
            if (
                position.direction == TradeDirection.SHORT
                and bar.open >= position.sl_price
            ):
                return bar.open, "SL"
            return position.sl_price, "SL"

        if hit_tp:
            return position.tp_price, "TP"

        return None
