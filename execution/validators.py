"""TradeSetupValidator: architectural validation boundary before planning."""

from models.trade_direction import TradeDirection
from models.trade_setup import TradeSetup


class TradeSetupValidationError(ValueError):
    """Raised when a TradeSetup fails structural validation."""


class TradeSetupValidator:
    """
    Architectural validation boundary between opportunity creation and planning.

    TradePlanner, ExecutionPolicy, PositionSizer, and executors must assume they
    receive a TradeSetup that has already passed through this validator.
    Do NOT duplicate validation concerns in those components.

    Future responsibilities (not implemented in this milestone):
    - Entry / stop / target consistency
    - Direction validation beyond presence
    - Instrument constraints
    - Order-type / entry-model validation
    - Expiry validation
    - Execution-policy compatibility checks
    - Strategy-specific validation hooks
    """

    def validate(self, setup: TradeSetup) -> TradeSetup:
        """
        Perform minimal structural checks; return the same setup if valid.

        This intentionally shallow check establishes the pipeline seam only.
        """
        # Architectural boundary: keep validation here — not in TradePlanner.
        if not setup.setup_id.strip():
            raise TradeSetupValidationError("setup_id must be non-empty")
        if not setup.symbol.strip():
            raise TradeSetupValidationError("symbol must be non-empty")
        if not isinstance(setup.direction, TradeDirection):
            raise TradeSetupValidationError(
                f"direction must be TradeDirection, got {setup.direction!r}"
            )
        if not setup.strategy_id.strip():
            raise TradeSetupValidationError("strategy_id must be non-empty")
        if setup.stop_hint is None:
            raise TradeSetupValidationError("stop_hint is required for planning")
        return setup
