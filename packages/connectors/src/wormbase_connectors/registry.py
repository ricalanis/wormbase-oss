"""Connector registry.

Single global registry plus a decorator for self-registration:

    @register_connector
    class MyConnector:
        kind = "my_thing"
        ...

The dashboard's ``/sources/new`` page (D4) reads from
:func:`default_registry` to populate its connector picker, so adding a
new connector is purely additive — no core code path changes.

Naming convention:

* Native connectors use a flat kind: ``csv_local``, ``postgres``,
  ``stripe``, ``hubspot``, etc.
* MCP-backed connectors (Block J4) prefix the vendor under an
  ``mcp:`` namespace: ``mcp:notion``, ``mcp:atlassian``,
  ``mcp:linear``, etc. The ``mcp:`` prefix is reserved — do not
  register native connectors with that prefix. The base
  :class:`wormbase_connectors.mcp.MCPConnector` declares
  ``kind = "mcp"`` for documentation but is not directly
  registered (it requires per-server config); presets register
  per-server subclasses instead.
"""

from __future__ import annotations

from typing import TypeVar

from .base import Connector

C = TypeVar("C", bound=type)


class ConnectorRegistry:
    """Holds the (kind -> Connector class) map.

    Tests construct fresh registries to avoid contaminating the global
    one. Production code reads :func:`default_registry`.
    """

    def __init__(self) -> None:
        self._by_kind: dict[str, type[Connector]] = {}

    def register(self, cls: type[Connector]) -> None:
        """Register a Connector class. Raises ValueError on duplicates.

        Duplicate-detection prevents a silent shadow when two modules
        define a connector with the same `kind`. The caller can call
        :meth:`unregister` first if intentional re-registration is
        needed (e.g. test isolation).
        """
        kind = getattr(cls, "kind", None)
        if not isinstance(kind, str) or not kind:
            raise ValueError(
                f"connector class {cls!r} must declare a non-empty `kind` str"
            )
        if kind in self._by_kind:
            raise ValueError(f"connector {kind!r} already registered")
        self._by_kind[kind] = cls

    def unregister(self, kind: str) -> None:
        self._by_kind.pop(kind, None)

    def get(self, kind: str) -> type[Connector] | None:
        return self._by_kind.get(kind)

    def all_kinds(self) -> list[str]:
        return sorted(self._by_kind.keys())

    def __len__(self) -> int:
        return len(self._by_kind)

    def __contains__(self, kind: object) -> bool:
        return isinstance(kind, str) and kind in self._by_kind


_default = ConnectorRegistry()


def register_connector(cls: C) -> C:
    """Decorator: ``@register_connector`` on a class adds it to the default registry.

    Idempotent across import cycles is NOT a goal — duplicate
    registration raises. Modules should be imported exactly once.
    """
    _default.register(cls)  # type: ignore[arg-type]
    return cls


def default_registry() -> ConnectorRegistry:
    """Return the process-wide default registry."""
    return _default


__all__ = ["ConnectorRegistry", "default_registry", "register_connector"]
