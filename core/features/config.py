"""Feature materialization settings (swings, range expansion, phase, MTF)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from core.validation import ConfigurationError


@dataclass(frozen=True)
class SwingDetectionConfig:
    left_bars: int
    right_bars: int
    minimum_swings: int


@dataclass(frozen=True)
class RangeExpansionConfig:
    recent_window: int
    historical_window: int
    low_ratio: float
    high_ratio: float


@dataclass(frozen=True)
class TrendStrengthConfig:
    """Categorical structure-score table (not confidence / probability).

    Values are looked up by trend label:
    BULLISH/BEARISH → ``aligned_structure_score``;
    RANGING → ``ranging_score``;
    UNKNOWN → ``unknown_score``.
    """

    aligned_structure_score: int
    ranging_score: int
    unknown_score: int


@dataclass(frozen=True)
class ScoreValueConfig:
    aligned: int
    partial: int
    neutral: int
    unknown: int
    range_expansion_low: int
    range_expansion_normal: int
    range_expansion_high: int


@dataclass(frozen=True)
class PhaseHeuristicConfig:
    compression_range_expansion_score_max: int
    strong_trend_score_min: int
    pullback_recent_window: int


@dataclass(frozen=True)
class IndicatorPackConfig:
    ema_fast_period: int
    ema_slow_period: int
    atr_period: int
    rsi_period: int
    macd_fast_period: int
    macd_slow_period: int
    macd_signal_period: int
    relative_volume_period: int


@dataclass(frozen=True)
class FeatureConfig:
    swing_detection: SwingDetectionConfig
    range_expansion: RangeExpansionConfig
    trend_strength: TrendStrengthConfig
    score_values: ScoreValueConfig
    multi_timeframe_mapping: dict[str, tuple[str, ...]]
    phase: PhaseHeuristicConfig
    indicators: IndicatorPackConfig


DEFAULT_FEATURE_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "market_structure.json"
)


def default_feature_config() -> FeatureConfig:
    """Built-in defaults matching legacy market_structure.json semantics."""
    return FeatureConfig(
        swing_detection=SwingDetectionConfig(left_bars=2, right_bars=2, minimum_swings=2),
        range_expansion=RangeExpansionConfig(
            recent_window=5,
            historical_window=20,
            low_ratio=0.7,
            high_ratio=1.3,
        ),
        trend_strength=TrendStrengthConfig(
            aligned_structure_score=85,
            ranging_score=35,
            unknown_score=0,
        ),
        score_values=ScoreValueConfig(
            aligned=85,
            partial=55,
            neutral=35,
            unknown=0,
            range_expansion_low=35,
            range_expansion_normal=65,
            range_expansion_high=85,
        ),
        multi_timeframe_mapping={
            "M1": ("M15", "M30", "H1", "H4"),
            "M15": ("M30", "H1", "H4"),
            "M30": ("H1", "H4"),
            "H1": ("H4",),
        },
        phase=PhaseHeuristicConfig(
            compression_range_expansion_score_max=35,
            strong_trend_score_min=70,
            pullback_recent_window=3,
        ),
        indicators=IndicatorPackConfig(
            ema_fast_period=20,
            ema_slow_period=50,
            atr_period=14,
            rsi_period=14,
            macd_fast_period=12,
            macd_slow_period=26,
            macd_signal_period=9,
            relative_volume_period=20,
        ),
    )


def load_feature_config(config_path: Path) -> FeatureConfig:
    """Load feature settings from JSON (supports legacy market_structure.json keys)."""
    with config_path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ConfigurationError("Feature configuration root must be an object")

    swing = _required_object(payload, "swing_detection")
    # Legacy key "momentum" means range expansion (body-size ratio).
    range_src = payload.get("range_expansion")
    if range_src is None:
        range_src = _required_object(payload, "momentum")
    elif not isinstance(range_src, dict):
        raise ConfigurationError("Invalid object: range_expansion")

    trend_src = payload.get("trend_scoring")
    if not isinstance(trend_src, dict):
        trend_src = {}

    scores_src = payload.get("component_score_values")
    if not isinstance(scores_src, dict):
        scores_src = {}

    phase_src = _required_object(payload, "market_phase")
    ema_src = payload.get("ema")
    if not isinstance(ema_src, dict):
        ema_src = {"fast_period": 20, "slow_period": 50}

    indicators_src = payload.get("indicators")
    if not isinstance(indicators_src, dict):
        indicators_src = {}

    mapping = _read_timeframe_mapping(payload)

    config = FeatureConfig(
        swing_detection=SwingDetectionConfig(
            left_bars=_required_int(swing, "left_bars"),
            right_bars=_required_int(swing, "right_bars"),
            minimum_swings=_required_int(swing, "minimum_swings"),
        ),
        range_expansion=RangeExpansionConfig(
            recent_window=_required_int(range_src, "recent_window"),
            historical_window=_required_int(range_src, "historical_window"),
            low_ratio=_required_float(range_src, "low_ratio"),
            high_ratio=_required_float(range_src, "high_ratio"),
        ),
        trend_strength=TrendStrengthConfig(
            aligned_structure_score=_optional_int(
                trend_src, "aligned_structure_score", 85
            ),
            ranging_score=_optional_int(trend_src, "ranging_score", 35),
            unknown_score=_optional_int(trend_src, "unknown_score", 0),
        ),
        score_values=ScoreValueConfig(
            aligned=_optional_int(scores_src, "aligned", 85),
            partial=_optional_int(scores_src, "partial", 55),
            neutral=_optional_int(scores_src, "neutral", 35),
            unknown=_optional_int(scores_src, "unknown", 0),
            range_expansion_low=_optional_int(
                scores_src, "momentum_low", _optional_int(scores_src, "range_expansion_low", 35)
            ),
            range_expansion_normal=_optional_int(
                scores_src,
                "momentum_normal",
                _optional_int(scores_src, "range_expansion_normal", 65),
            ),
            range_expansion_high=_optional_int(
                scores_src,
                "momentum_high",
                _optional_int(scores_src, "range_expansion_high", 85),
            ),
        ),
        multi_timeframe_mapping=mapping,
        phase=PhaseHeuristicConfig(
            compression_range_expansion_score_max=_required_int(
                phase_src, "compression_momentum_score_max"
            )
            if "compression_momentum_score_max" in phase_src
            else _required_int(phase_src, "compression_range_expansion_score_max"),
            strong_trend_score_min=_required_int(phase_src, "strong_trend_score_min"),
            pullback_recent_window=_required_int(phase_src, "pullback_recent_window"),
        ),
        indicators=IndicatorPackConfig(
            ema_fast_period=_required_int(ema_src, "fast_period"),
            ema_slow_period=_required_int(ema_src, "slow_period"),
            atr_period=_optional_int(indicators_src, "atr_period", 14),
            rsi_period=_optional_int(indicators_src, "rsi_period", 14),
            macd_fast_period=_optional_int(indicators_src, "macd_fast_period", 12),
            macd_slow_period=_optional_int(indicators_src, "macd_slow_period", 26),
            macd_signal_period=_optional_int(indicators_src, "macd_signal_period", 9),
            relative_volume_period=_optional_int(
                indicators_src, "relative_volume_period", 20
            ),
        ),
    )
    _validate(config)
    return config


def _read_timeframe_mapping(payload: dict[str, object]) -> dict[str, tuple[str, ...]]:
    mapping = payload.get("multi_timeframe_mapping", {})
    if not isinstance(mapping, dict):
        raise ConfigurationError("Multi-timeframe mapping must be an object")
    parsed: dict[str, tuple[str, ...]] = {}
    for entry_timeframe, higher_timeframes in mapping.items():
        if not isinstance(entry_timeframe, str) or not isinstance(higher_timeframes, list):
            raise ConfigurationError(
                "Multi-timeframe mapping must map timeframe strings to lists"
            )
        parsed[entry_timeframe] = tuple(
            value for value in higher_timeframes if isinstance(value, str)
        )
        if len(parsed[entry_timeframe]) != len(higher_timeframes):
            raise ConfigurationError("Multi-timeframe confirmation entries must be strings")
    return parsed


def _required_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigurationError(f"Missing or invalid object: {key}")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ConfigurationError(f"Missing or invalid integer: {key}")
    return value


def _optional_int(payload: dict[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise ConfigurationError(f"Invalid integer: {key}")
    return value


def _required_float(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float):
        raise ConfigurationError(f"Missing or invalid number: {key}")
    return float(value)


def _validate(config: FeatureConfig) -> None:
    if (
        config.swing_detection.left_bars < 1
        or config.swing_detection.right_bars < 1
        or config.swing_detection.minimum_swings < 1
    ):
        raise ConfigurationError("Swing detection parameters must be positive")
    if (
        config.range_expansion.recent_window < 1
        or config.range_expansion.historical_window < config.range_expansion.recent_window
    ):
        raise ConfigurationError("Invalid range-expansion windows")
    if (
        config.range_expansion.low_ratio <= 0
        or config.range_expansion.high_ratio <= 0
        or config.range_expansion.low_ratio >= config.range_expansion.high_ratio
    ):
        raise ConfigurationError("Invalid range-expansion ratios")
    if config.phase.pullback_recent_window < 1:
        raise ConfigurationError("Pullback recent window must be positive")
    if (
        config.indicators.ema_fast_period <= 0
        or config.indicators.ema_slow_period <= 0
        or config.indicators.ema_fast_period >= config.indicators.ema_slow_period
    ):
        raise ConfigurationError("Invalid EMA periods")
    if (
        config.indicators.atr_period < 1
        or config.indicators.rsi_period < 1
        or config.indicators.relative_volume_period < 1
    ):
        raise ConfigurationError("Indicator periods must be positive")
    if (
        config.indicators.macd_fast_period < 1
        or config.indicators.macd_slow_period < 1
        or config.indicators.macd_signal_period < 1
        or config.indicators.macd_fast_period >= config.indicators.macd_slow_period
    ):
        raise ConfigurationError("Invalid MACD periods")
