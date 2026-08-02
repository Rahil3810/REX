"""Entry point for the forex breakout trading platform."""

from datetime import datetime, timedelta
from pathlib import Path

from core.config_loader import load_pairs_config
from core.data_feed import MockDataFeed
from core.logger import setup_logger
from core.signal_engine import SignalEngine
from core.validation import validate_configuration_coverage
from core.zone_loader import load_zones
from models.bar import Bar

PROJECT_ROOT = Path(__file__).parent
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"


def build_demo_bars(symbol: str) -> list[Bar]:
    """
    Create sample bars that interact with EURUSD zones for demonstration.

    Replace MockDataFeed with a provider-specific DataFeed in production.
    """
    base_time = datetime(2026, 6, 20, 12, 0, 0)
    closes = [1.1490, 1.1510, 1.1530, 1.1660, 1.1640]

    bars: list[Bar] = []
    for index, close in enumerate(closes):
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=base_time + timedelta(minutes=15 * index),
                open=close - 0.0010,
                high=close + 0.0020,
                low=close - 0.0020,
                close=close,
            )
        )
    return bars


def main() -> None:
    logger = setup_logger("main", log_dir=LOG_DIR)

    pairs_config = load_pairs_config(CONFIG_DIR / "pairs.json")
    zone_books = load_zones(CONFIG_DIR / "zones.json")
    validate_configuration_coverage(pairs_config.pairs, zone_books)

    enabled_symbols = pairs_config.enabled_symbols()
    logger.info("Enabled symbols: %s", ", ".join(enabled_symbols))

    demo_bars: dict[str, list[Bar]] = {}
    for symbol in enabled_symbols:
        if symbol in zone_books:
            demo_bars[symbol] = build_demo_bars(symbol)

    data_feed = MockDataFeed(bars=demo_bars)
    engine = SignalEngine(data_feed=data_feed, zone_books=zone_books)

    for symbol in enabled_symbols:
        pair = pairs_config.get_pair(symbol)
        if pair is not None:
            engine.register_symbol(symbol, pair.base_timeframe)

    signals = engine.run(enabled_symbols)

    logger.info("--- Signal Summary ---")
    for signal in signals:
        logger.info("%s", signal.to_dict())


if __name__ == "__main__":
    main()
