"""View protocol and shared errors."""

from __future__ import annotations

from typing import Protocol

from core.features.context import FeatureContext
from core.features.types import MethodId


class UnsupportedMethodError(ValueError):
    """Raised when a View is asked for an unknown or unimplemented method_id."""


class FeatureView(Protocol):
    """Pure projection over an already-materialized FeatureContext."""

    def project(self, context: FeatureContext, method_id: MethodId | str) -> object:
        """Interpret features; never detect or materialize them."""


def require_method_id(method_id: MethodId | str | None) -> str:
    if method_id is None or str(method_id).strip() == "":
        raise UnsupportedMethodError(
            "method_id is required; silent defaults are not allowed"
        )
    return str(method_id)
