"""Public historical-data API for research and backtesting."""

from historical.bar_contract import (
    DatasetQualityReport,
    assess_dataset_quality,
    build_canonical_bar,
    normalize_provider_timestamp,
)
from historical.config import HistoricalDataConfig, load_historical_config
from historical.downloader import HistoricalDownloader
from historical.provider import HistoricalDataProvider
from historical.sources import DukascopyAdapter

__all__ = [
    "DatasetQualityReport",
    "DukascopyAdapter",
    "HistoricalDataConfig",
    "HistoricalDataProvider",
    "HistoricalDownloader",
    "assess_dataset_quality",
    "build_canonical_bar",
    "load_historical_config",
    "normalize_provider_timestamp",
]

