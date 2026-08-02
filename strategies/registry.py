"""Automatic discovery and lookup for strategy classes."""

import importlib
import inspect
import pkgutil
from collections.abc import Iterator

import strategies
from strategies.base_strategy import BaseStrategy


class StrategyRegistryError(ValueError):
    """Raised when a strategy cannot be registered or resolved."""


class StrategyRegistry:
    """Registry of strategy IDs to concrete strategy classes."""

    def __init__(self) -> None:
        self._strategies: dict[str, type[BaseStrategy]] = {}

    def register(self, strategy_class: type[BaseStrategy]) -> None:
        strategy_id = getattr(strategy_class, "strategy_id", "").strip()
        if not strategy_id:
            raise StrategyRegistryError(
                f"{strategy_class.__name__} must define a non-empty strategy_id"
            )
        for field_name in ("strategy_name", "description"):
            value = getattr(strategy_class, field_name, "")
            if not isinstance(value, str) or not value.strip():
                raise StrategyRegistryError(
                    f"{strategy_class.__name__} must define a non-empty {field_name}"
                )
        existing = self._strategies.get(strategy_id)
        if existing is not None and existing is not strategy_class:
            raise StrategyRegistryError(f"Duplicate strategy_id: {strategy_id}")
        self._strategies[strategy_id] = strategy_class

    def discover(self) -> "StrategyRegistry":
        """Import strategy modules and register all concrete BaseStrategy classes."""
        for module_info in pkgutil.iter_modules(strategies.__path__):
            if module_info.name.startswith("_") or module_info.name in {
                "base_strategy",
                "registry",
            }:
                continue
            module = importlib.import_module(f"strategies.{module_info.name}")
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if (
                    candidate.__module__ == module.__name__
                    and not candidate.__name__.startswith("_")
                    and issubclass(candidate, BaseStrategy)
                    and not inspect.isabstract(candidate)
                ):
                    self.register(candidate)
        return self

    def get(self, strategy_id: str) -> type[BaseStrategy]:
        try:
            return self._strategies[strategy_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._strategies)) or "none"
            raise StrategyRegistryError(
                f"Unknown strategy_id '{strategy_id}'. Available: {available}"
            ) from exc

    def create(self, strategy_id: str, **kwargs: object) -> BaseStrategy:
        return self.get(strategy_id)(**kwargs)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))

    def items(self) -> Iterator[tuple[str, type[BaseStrategy]]]:
        yield from sorted(self._strategies.items())


def build_default_registry() -> StrategyRegistry:
    """Return a registry populated from the strategies package."""
    return StrategyRegistry().discover()
