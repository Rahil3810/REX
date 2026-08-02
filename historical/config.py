"""Configuration loading and validation for historical data."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from historical.exceptions import HistoricalConfigurationError


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "historical_data.json"
)


@dataclass(frozen=True)
class HistoricalDataConfig:
    """Validated settings for downloading and storing historical candles."""

    provider: str
    symbols: tuple[str, ...]
    timeframe: str
    start_date: date
    end_date: date
    timeout_seconds: float
    retries: int
    retry_delay_seconds: float
    data_directory: Path
    overwrite_existing_files: bool
    duka_threads: int
    include_header: bool


def load_historical_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> HistoricalDataConfig:
    """Load historical-data settings from JSON.

    Args:
        config_path: JSON configuration path.

    Returns:
        Validated, strongly typed historical-data settings.

    Raises:
        HistoricalConfigurationError: If the file or any setting is invalid.
    """
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalConfigurationError(
            f"Unable to load historical configuration: {config_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise HistoricalConfigurationError("Historical configuration must be an object")

    provider = _string(payload, "provider").lower()
    symbols_value = payload.get("symbols")
    if not isinstance(symbols_value, list) or not symbols_value:
        raise HistoricalConfigurationError("symbols must be a non-empty list")
    symbols = tuple(_symbol(value) for value in symbols_value)
    if len(set(symbols)) != len(symbols):
        raise HistoricalConfigurationError("symbols cannot contain duplicates")

    start_date = _date(payload, "start_date")
    end_date = _date(payload, "end_date")
    config = HistoricalDataConfig(
        provider=provider,
        symbols=symbols,
        timeframe=_string(payload, "timeframe").upper(),
        start_date=start_date,
        end_date=end_date,
        timeout_seconds=_number(payload, "timeout_seconds"),
        retries=_integer(payload, "retries"),
        retry_delay_seconds=_number(payload, "retry_delay_seconds"),
        data_directory=Path(_string(payload, "data_directory")),
        overwrite_existing_files=_boolean(payload, "overwrite_existing_files"),
        duka_threads=_integer(payload, "duka_threads"),
        include_header=_boolean(payload, "include_header"),
    )
    _validate(config)
    return config


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HistoricalConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _symbol(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalConfigurationError("every symbol must be a non-empty string")
    return value.strip().upper()


def _date(payload: dict[str, object], key: str) -> date:
    try:
        return date.fromisoformat(_string(payload, key))
    except ValueError as exc:
        raise HistoricalConfigurationError(f"{key} must use YYYY-MM-DD") from exc


def _number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HistoricalConfigurationError(f"{key} must be a number")
    return float(value)


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalConfigurationError(f"{key} must be an integer")
    return value


def _boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HistoricalConfigurationError(f"{key} must be a boolean")
    return value


def _validate(config: HistoricalDataConfig) -> None:
    if config.provider != "dukascopy":
        raise HistoricalConfigurationError("provider must currently be 'dukascopy'")
    if config.timeframe != "M1":
        raise HistoricalConfigurationError("timeframe must currently be 'M1'")
    if config.start_date > config.end_date:
        raise HistoricalConfigurationError("start_date cannot be after end_date")
    if config.timeout_seconds <= 0:
        raise HistoricalConfigurationError("timeout_seconds must be positive")
    if config.retries < 0 or config.retry_delay_seconds < 0:
        raise HistoricalConfigurationError("retry settings cannot be negative")
    if config.duka_threads < 1:
        raise HistoricalConfigurationError("duka_threads must be positive")
