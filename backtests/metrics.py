"""Pure performance metric calculations for realized signal outcomes."""

from dataclasses import dataclass
from math import fsum


from models.closed_trade import ClosedTrade


@dataclass(frozen=True)
class PerformanceMetrics:
    total_signals: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float | None
    average_win: float
    average_loss: float
    expectancy: float
    max_drawdown: float
    largest_win: float
    largest_loss: float
    total_trades: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    ambiguous_exits: int = 0
    ambiguous_rate: float = 0.0
    avg_holding_duration: float = 0.0


def calculate_max_drawdown(outcomes: list[float]) -> float:
    """Return the largest peak-to-trough decline in cumulative outcome units."""
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for outcome in outcomes:
        equity += outcome
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def calculate_metrics(
    total_signals: int,
    realized_outcomes: list[float],
) -> PerformanceMetrics:
    """Calculate metrics without assuming how a strategy defines an outcome."""
    wins = [value for value in realized_outcomes if value > 0]
    losses = [value for value in realized_outcomes if value < 0]
    decided = len(wins) + len(losses)
    gross_profit = fsum(wins)
    gross_loss = abs(fsum(losses))

    profit_factor: float | None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = None

    return PerformanceMetrics(
        total_signals=total_signals,
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / decided * 100.0) if decided else 0.0,
        profit_factor=profit_factor,
        average_win=(gross_profit / len(wins)) if wins else 0.0,
        average_loss=(fsum(losses) / len(losses)) if losses else 0.0,
        expectancy=(fsum(realized_outcomes) / len(realized_outcomes))
        if realized_outcomes
        else 0.0,
        max_drawdown=calculate_max_drawdown(realized_outcomes),
        largest_win=max(wins, default=0.0),
        largest_loss=min(losses, default=0.0),
    )


def calculate_trade_metrics(
    total_signals: int,
    closed_trades: list[ClosedTrade],
) -> PerformanceMetrics:
    """Calculate performance metrics based on closed positions P&L."""
    if not closed_trades:
        return PerformanceMetrics(
            total_signals=total_signals,
            wins=0,
            losses=0,
            win_rate=0.0,
            profit_factor=None,
            average_win=0.0,
            average_loss=0.0,
            expectancy=0.0,
            max_drawdown=0.0,
            largest_win=0.0,
            largest_loss=0.0,
            total_trades=0,
            consecutive_wins=0,
            consecutive_losses=0,
            ambiguous_exits=0,
            ambiguous_rate=0.0,
            avg_holding_duration=0.0,
        )

    pnl_list = [trade.pnl_r for trade in closed_trades]
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]
    decided = len(wins) + len(losses)
    
    gross_profit = fsum(wins)
    gross_loss = abs(fsum(losses))
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    
    # Calculate consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    curr_consec_wins = 0
    curr_consec_losses = 0
    for pnl in pnl_list:
        if pnl > 0:
            curr_consec_wins += 1
            max_consec_wins = max(max_consec_wins, curr_consec_wins)
            curr_consec_losses = 0
        elif pnl < 0:
            curr_consec_losses += 1
            max_consec_losses = max(max_consec_losses, curr_consec_losses)
            curr_consec_wins = 0
        else:
            curr_consec_wins = 0
            curr_consec_losses = 0

    ambiguous_count = sum(1 for t in closed_trades if t.close_reason == "AMBIGUITY")
    ambiguous_rate = (ambiguous_count / len(closed_trades) * 100.0)
    
    total_duration = sum(t.holding_duration_candles for t in closed_trades)
    avg_holding_duration = total_duration / len(closed_trades)

    return PerformanceMetrics(
        total_signals=total_signals,
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / decided * 100.0) if decided else 0.0,
        profit_factor=profit_factor,
        average_win=(gross_profit / len(wins)) if wins else 0.0,
        average_loss=(fsum(losses) / len(losses)) if losses else 0.0,
        expectancy=fsum(pnl_list) / len(pnl_list),
        max_drawdown=calculate_max_drawdown(pnl_list),
        largest_win=max(wins, default=0.0),
        largest_loss=min(losses, default=0.0),
        total_trades=len(closed_trades),
        consecutive_wins=max_consec_wins,
        consecutive_losses=max_consec_losses,
        ambiguous_exits=ambiguous_count,
        ambiguous_rate=ambiguous_rate,
        avg_holding_duration=avg_holding_duration,
    )

