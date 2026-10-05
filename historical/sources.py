"""Provider-agnostic remote historical bar sources.

``HistoricalDataProvider`` (``historical.provider``) remains the **local**
reader over ``HistoricalStorage``. This module defines the **remote fetch**
boundary used by downloaders:

    Dukascopy (duka) → DukascopyAdapter → canonical REX Bar[] → HistoricalStorage

Adapters must not compute indicators, swings, BOS, zones, or MarketState.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from historical.bar_contract import validate_bar_sequence
from historical.exceptions import HistoricalDownloadError, UnsupportedHistoricalDataError
from historical.parser import HistoricalDataParser
from models.bar import Bar

if TYPE_CHECKING:
    from historical.downloader import DukaRunner


class HistoricalBarSource(Protocol):
    """Remote source that yields canonical REX bars for an interval."""

    provider_id: str

    def fetch_bars(
        self,
        instrument: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> list[Bar]:
        """Fetch and map provider data into validated REX bars.

        Args:
            instrument: Symbol / instrument id (e.g. EURUSD).
            timeframe: Candle timeframe (currently M1 for Dukascopy path).
            start: Inclusive start date (provider calendar date).
            end: Inclusive end date (provider calendar date).

        Returns:
            Chronologically ordered canonical bars (naive UTC timestamps).
        """
        ...


class DukascopyAdapter:
    """Dukascopy historical adapter via the open-source ``duka`` downloader.

    Responsibilities:
    - invoke duka download mechanics (through injectable ``DukaRunner``)
    - parse provider CSV
    - map timestamps to naive UTC and fields to REX OHLCV
    - validate bars / surface provider failures

    Non-responsibilities: indicators, HTF, swings, BOS, zones, MarketState.
    """

    provider_id = "dukascopy"

    def __init__(
        self,
        runner: DukaRunner | None = None,
        parser: HistoricalDataParser | None = None,
        *,
        timeout_seconds: float = 3600.0,
        threads: int = 5,
        include_header: bool = True,
        supported_timeframe: str = "M1",
    ) -> None:
        if runner is None:
            from historical.downloader import DukaCommandRunner

            runner = DukaCommandRunner()
        self.runner = runner
        self.parser = parser or HistoricalDataParser()
        self.timeout_seconds = timeout_seconds
        self.threads = threads
        self.include_header = include_header
        self.supported_timeframe = supported_timeframe.upper()

    def fetch_bars(
        self,
        instrument: str,
        timeframe: str,
        start: date,
        end: date,
    ) -> list[Bar]:
        symbol = instrument.strip().upper()
        tf = timeframe.strip().upper()
        if not symbol:
            raise UnsupportedHistoricalDataError("instrument is required")
        if tf != self.supported_timeframe:
            raise UnsupportedHistoricalDataError(
                f"Dukascopy adapter currently supports {self.supported_timeframe} only, "
                f"got {tf}"
            )
        if start > end:
            raise ValueError("start cannot be after end")

        try:
            with tempfile.TemporaryDirectory(prefix="rex-duka-adapter-") as directory:
                source = self.runner.download(
                    symbol=symbol,
                    start_date=start,
                    end_date=end,
                    timeframe=tf,
                    destination=Path(directory),
                    timeout_seconds=self.timeout_seconds,
                    threads=self.threads,
                    include_header=self.include_header,
                )
                bars = self.parser.parse_file(source, symbol)
        except UnsupportedHistoricalDataError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise HistoricalDownloadError(
                f"Dukascopy fetch failed for {symbol} {tf} {start}..{end}: {exc}"
            ) from exc

        if not bars:
            raise HistoricalDownloadError(
                f"Dukascopy returned no {tf} bars for {symbol} {start}..{end}"
            )
        return validate_bar_sequence(bars)
