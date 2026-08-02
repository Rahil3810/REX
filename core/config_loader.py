"""Load trading pair configuration from config/pairs.json."""

import json
from dataclasses import dataclass
from pathlib import Path

from core.validation import validate_pair_entries

@dataclass(frozen=True)
class PairConfig:
    """Configuration for a single trading pair."""

    symbol: str
    enabled: bool
    base_timeframe: str
    description: str


@dataclass(frozen=True)
class PairsConfig:
    """Collection of pair configurations."""

    pairs: tuple[PairConfig, ...]

    def enabled_symbols(self) -> list[str]:
        """Return symbols that are marked as enabled for trading."""
        return [pair.symbol for pair in self.pairs if pair.enabled]

    def get_pair(self, symbol: str) -> PairConfig | None:
        """Return configuration for a symbol, or None if not configured."""
        for pair in self.pairs:
            if pair.symbol == symbol:
                return pair
        return None


def load_pairs_config(config_path: Path) -> PairsConfig:
    """
    Load pair configuration from a JSON file.

    Expected format:
        {
          "pairs": [
            {
              "symbol": "EURUSD",
              "enabled": true,
              "base_timeframe": "15m",
              "description": "Euro / US Dollar"
            }
          ]
        }
    """
    with config_path.open(encoding="utf-8") as file:
        raw = json.load(file)

    if not isinstance(raw, dict):
        raise ValueError("Pair configuration root must be a JSON object")
    entries = raw.get("pairs", [])
    validate_pair_entries(entries)

    pairs = tuple(
        PairConfig(
            symbol=entry["symbol"],
            enabled=entry.get("enabled", True),
            base_timeframe=entry.get("base_timeframe", "15m"),
            description=entry.get("description", ""),
        )
        for entry in entries
    )

    return PairsConfig(pairs=pairs)
