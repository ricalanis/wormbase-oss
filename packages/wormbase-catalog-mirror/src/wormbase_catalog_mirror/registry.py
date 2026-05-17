"""CatalogSource registry — kind → class lookup.

Mirrors the registration pattern of ``SurfaceDriver`` / ``ChannelAdapter``:
adding a CatalogSource is a class + registry entry. No core-code change.

Day-one impls:

* ``"dbt"``       → ``DbtManifestCatalogSource``
* ``"snowflake"`` → ``SnowflakeNativeCatalogSource``

Wave 1.1+ adds further impls via ``register_catalog_source`` without
touching any consumer code.

Note on construction: ``DbtManifestCatalogSource`` requires a
``manifest_path``; the wire / source-builder caller is responsible for
constructing the concrete instance (or passing
``source.catalog_source`` pre-built). ``resolve_catalog_source`` returns
the *class* so callers can introspect / type-check; instantiation is
caller-owned because per-Source kwargs vary.
"""
from __future__ import annotations

from typing import Type

from .implementations.dbt_manifest import DbtManifestCatalogSource
from .implementations.snowflake_native import SnowflakeNativeCatalogSource
from .protocol import CatalogSource


_REGISTRY: dict[str, Type[CatalogSource]] = {
    "dbt": DbtManifestCatalogSource,
    "snowflake": SnowflakeNativeCatalogSource,
}


def resolve_catalog_source(kind: str) -> Type[CatalogSource]:
    """Return the CatalogSource class registered for ``kind``.

    Raises ``KeyError`` when no implementation is registered. Callers
    instantiate the returned class with whatever per-Source kwargs the
    concrete impl requires (e.g. ``DbtManifestCatalogSource(manifest_path=...)``).
    """
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise KeyError(
            f"no CatalogSource registered for kind={kind!r} "
            f"(known: {sorted(_REGISTRY)})"
        )
    return cls


def register_catalog_source(
    kind: str, impl: Type[CatalogSource],
) -> None:
    """Register an additional CatalogSource implementation.

    Used by Wave 1.1+ vendors (Cube, Malloy, LookML, Atlan) to slot
    in without modifying this module. Re-registering an existing
    ``kind`` is allowed; the most-recent registration wins.
    """
    _REGISTRY[kind] = impl


def known_catalog_kinds() -> tuple[str, ...]:
    """Tuple of registered ``kind`` strings, sorted alphabetically."""
    return tuple(sorted(_REGISTRY))


__all__ = [
    "known_catalog_kinds",
    "register_catalog_source",
    "resolve_catalog_source",
]
