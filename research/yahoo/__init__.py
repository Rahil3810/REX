"""Yahoo Finance research package (data-source experiments only)."""

from research.yahoo.adapter import (
    DATA_SOURCE,
    MIN_WARMUP_BARS,
    YAHOO_TICKER_EURUSD,
    YahooFetchResult,
    YahooH1QualityAudit,
    audit_yahoo_h1_bars,
    dataframe_to_bars,
    fetch_yahoo_h1,
    normalize_yahoo_timestamp,
    split_warmup_and_analysis,
)

__all__ = [
    "DATA_SOURCE",
    "MIN_WARMUP_BARS",
    "YAHOO_TICKER_EURUSD",
    "YahooFetchResult",
    "YahooH1QualityAudit",
    "audit_yahoo_h1_bars",
    "dataframe_to_bars",
    "fetch_yahoo_h1",
    "normalize_yahoo_timestamp",
    "split_warmup_and_analysis",
]
