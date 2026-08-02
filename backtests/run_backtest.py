from datetime import date
from pathlib import Path

from backtests.backtest_runner import BacktestRunner
from core.zone_loader import load_zones
from historical.provider import HistoricalDataProvider
from strategies.breakout import BreakoutStrategy

print("Loading zones...")
zone_books = load_zones(Path("config/zones.json"))
zone_book = zone_books["EURUSD"]
print(f"✓ Loaded {len(zone_book.zones)} zones")

print("Loading historical data...")
provider = HistoricalDataProvider()

bars = provider.get_bars(
    symbol="EURUSD",
    timeframe="M1",
    start_date=date(2026, 2, 1),
    end_date=date(2026, 2, 28),
)

print(f"✓ Loaded {len(bars)} bars")

print("Creating strategy...")
strategy = BreakoutStrategy(zone_book)

print("Running backtest...")

result = BacktestRunner().run(strategy, bars)

print("\n========== RESULTS ==========")
print(f"Strategy : {result.strategy_name}")
print(f"Signals  : {result.total_signals}")
print(f"Wins     : {result.wins}")
print(f"Losses   : {result.losses}")
print(f"Win Rate : {result.win_rate}%")
print(f"Profit Factor : {result.profit_factor}")
print(f"Expectancy    : {result.expectancy}")
print("============================")

print("\nFirst 10 signals:\n")

for signal in result.signal_outcomes[:10]:
    print(signal)