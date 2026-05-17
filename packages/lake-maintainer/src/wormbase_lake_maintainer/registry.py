"""SourceRegistry — per-tenant MaintainableSource catalog.

Single-loop, single-tenant. The Source-connect lifecycle hook in
worm-core (Block G2) calls ``register(source)`` after a connector
hands back its AcquirableSource impl; the matching deregister fires
on source-retire.

The registry only owns the set of MaintainableSources. Wiring
maintenance Reactivities into W5a's ReactivityRegistry is the caller's
job (factory + ReactivityRegistry.register, see Block G2).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from wormbase_lake_maintainer.factory import make_maintenance_reactivities
from wormbase_lake_maintainer.types import SourceFamily


@dataclass
class SourceRegistry:
    """In-memory MaintainableSource registry, keyed on source id.

    Deduplicates by id (re-registering an existing source is a no-op).
    Family filter on list_sources lets callers fan out per family for
    family-specific maintenance dashboards.
    """

    company_id: UUID
    _sources: dict[UUID, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def register(self, source: Any) -> None:
        async with self._lock:
            self._sources[source.id] = source

    async def deregister(self, source_id: UUID) -> None:
        async with self._lock:
            self._sources.pop(source_id, None)

    async def list_sources(
        self, *, family: SourceFamily | None = None,
    ) -> list[Any]:
        async with self._lock:
            sources = list(self._sources.values())
        if family is None:
            return sources
        return [s for s in sources if s.family == family]


async def wire_maintenance_for_source(
    *,
    source: Any,
    source_registry: SourceRegistry,
    reactivity_registry: Any,
) -> list[Any]:
    """Wire one MaintainableSource into both registries.

    Side effects:
    1. ``source_registry.register(source)`` — adds to the per-tenant
       MaintainableSource catalog.
    2. ``reactivity_registry.register(reactivity)`` — for each of the
       four Reactivities the factory produces.

    Returns the list of registered Reactivity instances so the caller
    can record them in the audit log.

    Caller is the worm-core source-builder (Block G3); a deregister
    helper is intentionally not provided in v1 — Source retirement is
    a Phase 2 concern.
    """
    await source_registry.register(source)
    reactivities = make_maintenance_reactivities(source=source)
    for reactivity in reactivities:
        reactivity_registry.register(reactivity)
    return reactivities


__all__ = ["SourceRegistry", "wire_maintenance_for_source"]
