"""CatalogSource Protocol — the 4th durable Protocol in WormBase.

Mirrors structure (not data) from an upstream lake. Day-one implementations:
DbtManifestCatalogSource, SnowflakeNativeCatalogSource. Future technologies
add as a class + registry entry — no core-code change (per SurfaceDriver / ChannelAdapter
extensibility pattern).
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from .types import CatalogCapability, CatalogDelta, CatalogSnapshot, ExternalPolicy, LineageGraph, MetricDefinition


class AuthHandle(Protocol):
    """Marker type — implementations return whatever opaque handle their auth flow needs."""
    ...


@runtime_checkable
class CatalogSource(Protocol):
    kind: str                                    # "dbt" | "snowflake" | ...
    capability: frozenset[CatalogCapability]

    async def authenticate(self, secrets: dict[str, str]) -> AuthHandle: ...
    async def discover_catalog(self, handle: AuthHandle) -> CatalogSnapshot: ...
    async def discover_lineage(self, handle: AuthHandle, resource_id: str) -> LineageGraph: ...
    async def discover_policies(self, handle: AuthHandle, resource_id: str) -> list[ExternalPolicy]: ...
    async def discover_metrics(self, handle: AuthHandle) -> list[MetricDefinition]: ...

    async def watch_changes(self, handle: AuthHandle) -> AsyncIterator[CatalogDelta]:
        """Optional capability — implementations without push-CDC raise StopAsyncIteration."""
        ...
