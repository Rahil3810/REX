"""Weighted confidence calculation for component scores."""

from collections.abc import Mapping

from core.market_structure.context import ComponentId
from models.market_structure import ComponentScore


class ConfidenceCalculator:
    """Calculate confidence from configured component weights."""

    def __init__(self, weights: dict[str, float]) -> None:
        """Initialize the calculator.

        Args:
            weights: Component weights keyed by stable serialized identifier.
        """
        self._weights = weights

    def calculate(
        self, component_scores: Mapping[ComponentId, ComponentScore]
    ) -> int:
        """Calculate a clamped weighted-average confidence score.

        Args:
            component_scores: Scores keyed by typed component identifiers.

        Returns:
            An integer confidence score between zero and one hundred.
        """
        weighted_total = 0.0
        active_weight_total = 0.0
        for component_id, score in component_scores.items():
            weight = self._weights.get(component_id.value)
            if weight is None:
                continue
            weighted_total += score.score * weight
            active_weight_total += weight
        if active_weight_total == 0:
            return 0
        return max(0, min(100, round(weighted_total / active_weight_total)))
