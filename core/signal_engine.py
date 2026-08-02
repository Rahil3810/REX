"""Orchestrates data feeds, zone books, and strategy evaluation."""

from dataclasses import dataclass, field

from core.chart_analyzer import ChartAnalyzer
from core.data_feed import DataFeed
from core.logger import setup_logger
from core.signal_enricher import enrich_signal
from core.session_manager import SessionManager
from models.bar import Bar
from models.signal import Signal
from models.zone import ZoneBook
from strategies.breakout import BreakoutStrategy

logger = setup_logger("signal_engine")


@dataclass
class SignalEngine:
    """
    Central coordinator for signal generation.

    Wires a data feed to one or more strategies per symbol. Future extensions:
    - Backtest replay mode
    - Additional measurable strategy implementations
    """

    data_feed: DataFeed
    zone_books: dict[str, ZoneBook]
    chart_analyzer: ChartAnalyzer | None = None
    session_manager: SessionManager | None = None
    _strategies: dict[str, BreakoutStrategy] = field(default_factory=dict)
    _signals: list[Signal] = field(default_factory=list)
    _history: dict[str, list[Bar]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.chart_analyzer is None:
            self.chart_analyzer = ChartAnalyzer()
        if self.session_manager is None:
            self.session_manager = SessionManager()

        for symbol, zone_book in self.zone_books.items():
            self._strategies[symbol] = BreakoutStrategy(zone_book=zone_book)
            self._history[symbol] = []
            logger.info(
                "Registered breakout strategy for %s with %d zone(s)",
                symbol,
                len(zone_book.zones),
            )

    def register_symbol(self, symbol: str, timeframe: str) -> None:
        """Subscribe the data feed and ensure a strategy exists for the symbol."""
        self.data_feed.subscribe(symbol, timeframe)

        if symbol not in self._strategies and symbol in self.zone_books:
            self._strategies[symbol] = BreakoutStrategy(
                zone_book=self.zone_books[symbol]
            )
        if symbol not in self._history:
            self._history[symbol] = []

    def process_bar(self, bar: Bar) -> list[Signal]:
        """Evaluate a single bar, enrich signals with context, and collect them."""
        strategy = self._strategies.get(bar.symbol)
        if strategy is None:
            logger.warning("No strategy registered for symbol %s", bar.symbol)
            return []

        if bar.symbol not in self._history:
            self._history[bar.symbol] = []
        self._history[bar.symbol].append(bar)

        generator = getattr(strategy, "generate_signals", None)
        if callable(generator):
            raw_signals = generator(self._history[bar.symbol])
        else:
            raw_signals = strategy.evaluate(bar)
        enriched_signals = self._enrich_signals(bar, raw_signals)
        self._signals.extend(enriched_signals)
        return enriched_signals

    def _enrich_signals(self, bar: Bar, signals: list[Signal]) -> list[Signal]:
        """Attach market context to each signal when a zone book is available."""
        zone_book = self.zone_books.get(bar.symbol)
        if zone_book is None or self.chart_analyzer is None or not signals:
            return signals

        context = self.chart_analyzer.analyze(zone_book, bar.close)
        enriched: list[Signal] = []

        for signal in signals:
            enriched_signal = enrich_signal(signal, context, zone_book)
            if enriched_signal.is_enriched:
                logger.info(
                    "Enriched signal: %s",
                    enriched_signal.to_dict(),
                )
            enriched.append(enriched_signal)

        return enriched

    def run(self, symbols: list[str]) -> list[Signal]:
        """
        Stream bars from the data feed for each symbol and evaluate strategies.

        Returns all signals generated during the run.
        """
        session_info = self.session_manager.get_current_session()
        logger.info(
            "Session (IST): %s | overlap=%s | high_liquidity=%s",
            session_info.session.value,
            session_info.overlap,
            session_info.high_liquidity,
        )

        all_signals: list[Signal] = []

        for symbol in symbols:
            logger.info("Processing bars for %s", symbol)
            for bar in self.data_feed.stream_bars(symbol):
                signals = self.process_bar(bar)
                all_signals.extend(signals)

        logger.info("Run complete — %d signal(s) generated", len(all_signals))
        return all_signals

    def get_signals(self) -> list[Signal]:
        """Return all signals collected since engine initialization."""
        return list(self._signals)

    def clear_signals(self) -> None:
        """Clear the internal signal buffer."""
        self._signals.clear()

    def reset(self) -> None:
        """Reset the signal buffer and per-symbol history to prevent history leaking."""
        self.clear_signals()
        for symbol in self._history:
            self._history[symbol].clear()
