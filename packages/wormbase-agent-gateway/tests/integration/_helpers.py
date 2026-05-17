"""Shared helpers for integration tests (importable, unlike conftest.py)."""
from __future__ import annotations

from typing import Any


def unwrap(result: Any) -> dict[str, Any]:
    """Extract the structured payload from a FastMCP CallToolResult.

    FastMCP wraps union-return-type tools as ``{"result": {...}}`` in
    ``structured_content``; non-union returns are flat dicts. The
    helper hides this so tests read ``unwrap(r)`` regardless of
    declared return shape.
    """
    sc = result.structured_content
    if sc is None:
        if hasattr(result, "data") and result.data is not None:
            try:
                return result.data.model_dump()
            except AttributeError:
                return dict(result.data)  # type: ignore[arg-type]
        return {}
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc
