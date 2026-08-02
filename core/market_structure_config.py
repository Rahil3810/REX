"""Load MarketStructureAnalyzer configuration."""

from dataclasses import dataclass
import json
from pathlib import Path

from core.validation import ConfigurationError


@dataclass(frozen=True)
class EmaConfig:
    fast_period: int
    slow_period: int


@dataclass(frozen=True)
class SwingDetectionConfig:
    left_bars: int
    right_bars: int
    minimum_swings: int


@dataclass(frozen=True)
class MomentumConfig:
    recent_window: int
    historical_window: int
    low_ratio: float
    high_ratio: float


@dataclass(frozen=True)
class TrendScoringConfig:
    aligned_structure_score: int
    partial_structure_score: int
    ranging_score: int
    unknown_score: int


@dataclass(frozen=True)
class ComponentScoreValueConfig:
    aligned: int
    partial: int
    neutral: int
    unknown: int
    momentum_low: int
    momentum_normal: int
    momentum_high: int


@dataclass(frozen=True)
class ConfidenceThresholdConfig:
    high: int
    medium: int
    low: int


@dataclass(frozen=True)
class MarketPhaseConfig:
    compression_momentum_score_max: int
    strong_trend_score_min: int
    pullback_recent_window: int


@dataclass(frozen=True)
class MarketStructureAnalyzerConfig:
    component_weights: dict[str, float]
    ema: EmaConfig
    swing_detection: SwingDetectionConfig
    momentum: MomentumConfig
    trend_scoring: TrendScoringConfig
    component_score_values: ComponentScoreValueConfig
    confidence_thresholds: ConfidenceThresholdConfig
    multi_timeframe_mapping: dict[str, tuple[str, ...]]
    market_phase: MarketPhaseConfig
    future_scoring_parameters: dict[str, object]


def load_market_structure_config(config_path: Path) -> MarketStructureAnalyzerConfig:
    """Load and validate MarketStructureAnalyzer configuration from JSON."""
    with config_path.open(encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ConfigurationError("Market structure configuration root must be an object")

    config = MarketStructureAnalyzerConfig(
        component_weights=_read_weights(payload),
        ema=_read_ema(payload),
        swing_detection=_read_swing_detection(payload),
        momentum=_read_momentum(payload),
        trend_scoring=_read_trend_scoring(payload),
        component_score_values=_read_component_score_values(payload),
        confidence_thresholds=_read_confidence_thresholds(payload),
        multi_timeframe_mapping=_read_timeframe_mapping(payload),
        market_phase=_read_market_phase(payload),
        future_scoring_parameters=_read_optional_object(
            payload, "future_scoring_parameters"
        ),
    )
    _validate_config(config)
    return config


def _read_weights(payload: dict[str, object]) -> dict[str, float]:
    weights = _required_object(payload, "component_weights")
    parsed: dict[str, float] = {}
    for name, value in weights.items():
        if not isinstance(name, str) or not isinstance(value, int | float):
            raise ConfigurationError("Component weights must map names to numbers")
        parsed[name] = float(value)
    return parsed


def _read_ema(payload: dict[str, object]) -> EmaConfig:
    ema = _required_object(payload, "ema")
    return EmaConfig(
        fast_period=_required_int(ema, "fast_period"),
        slow_period=_required_int(ema, "slow_period"),
    )


def _read_swing_detection(payload: dict[str, object]) -> SwingDetectionConfig:
    swing = _required_object(payload, "swing_detection")
    return SwingDetectionConfig(
        left_bars=_required_int(swing, "left_bars"),
        right_bars=_required_int(swing, "right_bars"),
        minimum_swings=_required_int(swing, "minimum_swings"),
    )


def _read_momentum(payload: dict[str, object]) -> MomentumConfig:
    momentum = _required_object(payload, "momentum")
    return MomentumConfig(
        recent_window=_required_int(momentum, "recent_window"),
        historical_window=_required_int(momentum, "historical_window"),
        low_ratio=_required_float(momentum, "low_ratio"),
        high_ratio=_required_float(momentum, "high_ratio"),
    )


def _read_trend_scoring(payload: dict[str, object]) -> TrendScoringConfig:
    scoring = _required_object(payload, "trend_scoring")
    return TrendScoringConfig(
        aligned_structure_score=_required_int(scoring, "aligned_structure_score"),
        partial_structure_score=_required_int(scoring, "partial_structure_score"),
        ranging_score=_required_int(scoring, "ranging_score"),
        unknown_score=_required_int(scoring, "unknown_score"),
    )


def _read_component_score_values(
    payload: dict[str, object],
) -> ComponentScoreValueConfig:
    scores = _required_object(payload, "component_score_values")
    return ComponentScoreValueConfig(
        aligned=_required_int(scores, "aligned"),
        partial=_required_int(scores, "partial"),
        neutral=_required_int(scores, "neutral"),
        unknown=_required_int(scores, "unknown"),
        momentum_low=_required_int(scores, "momentum_low"),
        momentum_normal=_required_int(scores, "momentum_normal"),
        momentum_high=_required_int(scores, "momentum_high"),
    )


def _read_confidence_thresholds(
    payload: dict[str, object],
) -> ConfidenceThresholdConfig:
    thresholds = _required_object(payload, "confidence_thresholds")
    return ConfidenceThresholdConfig(
        high=_required_int(thresholds, "high"),
        medium=_required_int(thresholds, "medium"),
        low=_required_int(thresholds, "low"),
    )


def _read_timeframe_mapping(payload: dict[str, object]) -> dict[str, tuple[str, ...]]:
    mapping = _required_object(payload, "multi_timeframe_mapping")
    parsed: dict[str, tuple[str, ...]] = {}
    for entry_timeframe, higher_timeframes in mapping.items():
        if not isinstance(entry_timeframe, str) or not isinstance(
            higher_timeframes, list
        ):
            raise ConfigurationError(
                "Multi-timeframe mapping must map timeframe strings to lists"
            )
        parsed[entry_timeframe] = tuple(_require_string_list(higher_timeframes))
    return parsed


def _read_market_phase(payload: dict[str, object]) -> MarketPhaseConfig:
    phase = _required_object(payload, "market_phase")
    return MarketPhaseConfig(
        compression_momentum_score_max=_required_int(
            phase, "compression_momentum_score_max"
        ),
        strong_trend_score_min=_required_int(phase, "strong_trend_score_min"),
        pullback_recent_window=_required_int(phase, "pullback_recent_window"),
    )


def _required_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigurationError(f"Missing or invalid object: {key}")
    return value


def _read_optional_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ConfigurationError(f"Invalid object: {key}")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ConfigurationError(f"Missing or invalid integer: {key}")
    return value


def _required_float(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float):
        raise ConfigurationError(f"Missing or invalid number: {key}")
    return float(value)


def _require_string_list(values: list[object]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ConfigurationError(
                "Multi-timeframe confirmation entries must be strings"
            )
        parsed.append(value)
    return parsed


def _validate_config(config: MarketStructureAnalyzerConfig) -> None:
    if not config.component_weights:
        raise ConfigurationError("At least one component weight is required")
    if any(weight < 0 for weight in config.component_weights.values()):
        raise ConfigurationError("Component weights cannot be negative")
    if sum(config.component_weights.values()) <= 0:
        raise ConfigurationError("Component weights must have a positive total")
    if config.ema.fast_period <= 0 or config.ema.slow_period <= 0:
        raise ConfigurationError("EMA periods must be positive")
    if config.ema.fast_period >= config.ema.slow_period:
        raise ConfigurationError("Fast EMA period must be lower than slow EMA period")
    if (
        config.swing_detection.left_bars < 1
        or config.swing_detection.right_bars < 1
        or config.swing_detection.minimum_swings < 1
    ):
        raise ConfigurationError("Swing detection parameters must be positive")
    if (
        config.momentum.recent_window < 1
        or config.momentum.historical_window < config.momentum.recent_window
    ):
        raise ConfigurationError("Invalid momentum windows")
    if config.momentum.low_ratio <= 0 or config.momentum.high_ratio <= 0:
        raise ConfigurationError("Momentum ratios must be positive")
    if config.momentum.low_ratio >= config.momentum.high_ratio:
        raise ConfigurationError("Momentum low ratio must be below high ratio")
    for score in (
        config.trend_scoring.aligned_structure_score,
        config.trend_scoring.partial_structure_score,
        config.trend_scoring.ranging_score,
        config.trend_scoring.unknown_score,
        config.component_score_values.aligned,
        config.component_score_values.partial,
        config.component_score_values.neutral,
        config.component_score_values.unknown,
        config.component_score_values.momentum_low,
        config.component_score_values.momentum_normal,
        config.component_score_values.momentum_high,
        config.confidence_thresholds.high,
        config.confidence_thresholds.medium,
        config.confidence_thresholds.low,
        config.market_phase.compression_momentum_score_max,
        config.market_phase.strong_trend_score_min,
    ):
        if score < 0 or score > 100:
            raise ConfigurationError("Scores and thresholds must be within 0-100")
    if config.market_phase.pullback_recent_window < 1:
        raise ConfigurationError("Pullback recent window must be positive")
