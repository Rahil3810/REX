"""Exceptions raised by the historical-data subsystem."""


class HistoricalDataError(Exception):
    """Base exception for historical-data failures."""


class HistoricalConfigurationError(HistoricalDataError, ValueError):
    """Raised when historical-data configuration is invalid."""


class HistoricalDownloadError(HistoricalDataError):
    """Raised when a download cannot be completed after retries."""


class HistoricalParseError(HistoricalDataError, ValueError):
    """Raised when a historical CSV contains invalid market data."""


class HistoricalStorageError(HistoricalDataError):
    """Raised when historical data cannot be read or persisted."""


class UnsupportedHistoricalDataError(HistoricalDataError, ValueError):
    """Raised for unsupported providers, symbols, or timeframes."""
