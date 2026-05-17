"""DbtManifestCatalogSource — reads a vendored or local dbt manifest.json.

Per S1 spike findings:
- whitelist {model, seed} resource types (not just model — seeds appear as upstreams)
- ColumnMeta.type may be None (data_type populated only after `dbt docs generate`)
- snapshot_hash via sorted-JSON-canonicalization for drift baseline
- manifest_version v12 supported; v3 / older raises ManifestVersionUnsupportedError
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from ..errors import ManifestVersionUnsupportedError
from ..protocol import AuthHandle
from ..types import (
    CatalogCapability,
    CatalogDelta,
    CatalogSnapshot,
    ColumnMeta,
    ExternalPolicy,
    LineageEdge,
    LineageGraph,
    MetricDefinition,
    TableMeta,
)


SUPPORTED_MANIFEST_SCHEMAS = frozenset({
    "https://schemas.getdbt.com/dbt/manifest/v10.json",
    "https://schemas.getdbt.com/dbt/manifest/v11.json",
    "https://schemas.getdbt.com/dbt/manifest/v12.json",
})

# Per S1 finding — both model and seed are tableshaped; sources covered via lineage upstream refs
_TABLESHAPED_RESOURCE_TYPES = frozenset({"model", "seed"})


def parse_dbt_manifest(path: Path) -> CatalogSnapshot:
    raw = json.loads(path.read_text())

    schema_version = raw.get("metadata", {}).get("dbt_schema_version")
    if schema_version not in SUPPORTED_MANIFEST_SCHEMAS:
        raise ManifestVersionUnsupportedError(
            f"manifest schema {schema_version!r} not in supported set {sorted(SUPPORTED_MANIFEST_SCHEMAS)}"
        )

    nodes = raw.get("nodes") or {}
    metrics_raw = raw.get("metrics") or {}

    tables: list[TableMeta] = []
    edges: list[LineageEdge] = []

    for unique_id, node in nodes.items():
        if node.get("resource_type") not in _TABLESHAPED_RESOURCE_TYPES:
            continue
        cols = tuple(
            ColumnMeta(
                name=cname,
                type=cmeta.get("data_type"),
                description=cmeta.get("description") or None,
                tags=tuple(cmeta.get("tags") or ()),
            )
            for cname, cmeta in (node.get("columns") or {}).items()
        )
        tables.append(TableMeta(
            external_id=unique_id,
            name=node.get("name", ""),
            schema=node.get("schema"),
            database=node.get("database"),
            description=node.get("description") or None,
            columns=cols,
            tags=tuple(node.get("tags") or ()),
        ))
        for parent_id in (node.get("depends_on") or {}).get("nodes") or []:
            edges.append(LineageEdge(upstream=parent_id, downstream=unique_id))

    metrics: list[MetricDefinition] = []
    for mid, m in metrics_raw.items():
        metrics.append(MetricDefinition(
            name=m.get("name") or mid.rsplit(".", 1)[-1],
            expression=(m.get("filter") or {}).get("where_sql_template"),
            description=m.get("description"),
        ))

    return CatalogSnapshot(
        source_kind="dbt",
        tables=tuple(tables),
        lineage=LineageGraph(edges=tuple(edges)),
        policies=(),                # dbt doesn't surface enforcement policies
        metrics=metrics,
    )


@dataclass
class DbtManifestCatalogSource:
    """Reads dbt manifest.json from a configurable path.

    For production tenants the path comes from the Install record's manifest URI;
    for tests the path is provided directly.
    """
    manifest_path: Path
    kind: str = field(default="dbt", init=False)
    capability: frozenset[CatalogCapability] = field(
        default=frozenset({"schema", "lineage", "semantic_layer"}),
        init=False,
    )

    async def authenticate(self, secrets: dict[str, str]) -> AuthHandle:
        # No auth required for local-file manifests; secrets are for git-remote manifests in v1.1.
        return object()  # opaque handle

    async def discover_catalog(self, handle: AuthHandle) -> CatalogSnapshot:
        return parse_dbt_manifest(self.manifest_path)

    async def discover_lineage(self, handle: AuthHandle, resource_id: str) -> LineageGraph:
        snap = parse_dbt_manifest(self.manifest_path)
        return LineageGraph(edges=tuple(
            e for e in snap.lineage.edges if e.upstream == resource_id or e.downstream == resource_id
        ))

    async def discover_policies(self, handle: AuthHandle, resource_id: str) -> list[ExternalPolicy]:
        return []  # dbt doesn't define enforcement policies

    async def discover_metrics(self, handle: AuthHandle) -> list[MetricDefinition]:
        snap = parse_dbt_manifest(self.manifest_path)
        return list(snap.metrics)

    async def watch_changes(self, handle: AuthHandle) -> AsyncIterator[CatalogDelta]:
        # No push-CDC for static manifests; periodic re-discover via Reactivity is the path.
        if False:
            yield  # pragma: no cover
        return
