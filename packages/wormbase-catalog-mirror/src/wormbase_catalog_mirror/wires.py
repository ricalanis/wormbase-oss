"""wire_catalog_for_source — per-source catalog-mirror Reactivity wiring.

Per Wave 1 cleanup 1a (2026-05-11): catalog-mirror moves from boot-scope
(the 5th wire) to per-source registration, matching lake-maintainer's
canonical pattern at ``wire_maintenance_for_source``. The hub's
``source_builder.SourceBuilder.on_source_connected`` lifecycle hook
dispatches into this wire for any source carrying a ``catalog_source``
attribute (i.e. an upstream_mirror Source); ``wormbase_owned`` sources
fall through to lake-maintainer only.

Signature mirrors ``wire_maintenance_for_source`` exactly: async,
kwarg-only, ``source`` first, ``reactivity_registry`` last, returns the
flat list of Reactivities that were registered so the caller can record
them in the audit log. ``ledger`` rides alongside for symmetry with the
other install-scope wires and to surface the dependency at call sites —
catalog-mirror Reactivities consume the ledger via ``ReactivityContext``
at dispatch time, so the wire does not consume it directly.

Each source must expose:

* ``id``              — opaque source identifier (str or UUID, coerced to str)
* ``domain_id``       — owning domain for governance scoping
* ``catalog_source``  — a pre-constructed ``CatalogSource`` instance
                        (e.g. ``DbtManifestCatalogSource(manifest_path=...)``)
* ``secrets``         — dict[str, str] of authentication secrets (optional, defaults to {})

The wire does NOT construct the ``CatalogSource``: per-Source
construction kwargs vary (manifest path for dbt, none for snowflake),
so source-builder owns instantiation and the wire only registers the
Reactivities that observe the already-instantiated source.
"""
from __future__ import annotations

from typing import Any

from wormbase_ledger import InMemoryLedger, Ledger

from .reactivities import make_catalog_mirror_reactivities


async def wire_catalog_for_source(
    *,
    source: Any,
    ledger: Ledger | InMemoryLedger,
    reactivity_registry: Any,  # ReactivityRegistry — typed Any to keep
                                # this module's import surface light,
                                # mirroring lake-maintainer's wire.
) -> list[Any]:
    """Register catalog-mirror Reactivities for one upstream_mirror Source.

    Args:
        source: An upstream_mirror Source record. Read fields:
            ``source.id`` → source identifier (coerced to str);
            ``source.domain_id`` → owning domain id;
            ``source.catalog_source`` → pre-constructed ``CatalogSource``;
            ``source.secrets`` → optional ``dict[str, str]`` (default ``{}``).
        ledger: the production ``Ledger`` or test ``InMemoryLedger``.
            Held by reference for signature symmetry with the other
            wires; the Reactivities read it from
            ``ReactivityContext.ledger`` at dispatch time.
        reactivity_registry: the W5a ``ReactivityRegistry`` to register
            into. Typed ``Any`` to keep this module's imports light.

    Returns:
        The flat list of Reactivity instances that were registered for
        this source (two per upstream_mirror source — import + drift).

    Side effects:
        Constructs ``CatalogImportReactivity`` + ``CatalogDriftReactivity``
        via ``make_catalog_mirror_reactivities`` and registers each
        with ``reactivity_registry.register(r)``.
    """
    # ledger is held by reference; the Reactivity reads it from the
    # ReactivityContext.ledger that the registry threads at dispatch
    # time. We keep ``ledger`` in the wire signature for symmetry with
    # the other install-scope wires (and to surface the dependency at
    # wire-call sites).
    _ = ledger

    reactivities = make_catalog_mirror_reactivities(
        source_id=str(getattr(source, "id")),
        domain_id=str(getattr(source, "domain_id")),
        catalog_source=getattr(source, "catalog_source"),
        secrets=dict(getattr(source, "secrets", {}) or {}),
    )
    registered: list[Any] = []
    for r in reactivities:
        reactivity_registry.register(r)
        registered.append(r)
    return registered


__all__ = ["wire_catalog_for_source"]
