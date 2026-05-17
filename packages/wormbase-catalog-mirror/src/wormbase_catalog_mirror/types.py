"""Catalog-mirror value types — pydantic v2.

Frozen + deterministic hashing for drift detection. Per spike S1 finding:
ColumnMeta.type may be None (dbt doesn't always populate without docs generate).
Per spike S2 finding: ExternalPolicy.body may be None when caller lacks
APPLY privilege on the policy.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict


CatalogCapability = Literal["schema", "lineage", "policy", "semantic_layer", "quality"]
PolicyKind = Literal["masking", "row_access"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ColumnMeta(_Frozen):
    name: str
    type: str | None
    description: str | None
    tags: tuple[str, ...] = ()


class TableMeta(_Frozen):
    external_id: str           # upstream-stable id (e.g. dbt unique_id, snowflake fqn)
    name: str
    schema: str | None
    database: str | None
    description: str | None
    columns: tuple[ColumnMeta, ...]
    tags: tuple[str, ...] = ()


class LineageEdge(_Frozen):
    upstream: str
    downstream: str


class LineageGraph(_Frozen):
    edges: tuple[LineageEdge, ...]


class ExternalPolicy(_Frozen):
    name: str                       # fully-qualified for upstreams that scope policies
    policy_kind: PolicyKind
    body: str | None                # may be None if caller lacks APPLY priv (S2 finding)
    applied_to: tuple[str, ...] = ()


class MetricDefinition(_Frozen):
    """Semantic-layer metric — dbt MetricFlow / Cube / Malloy / LookML normalized form."""
    name: str
    expression: str | None = None
    time_grain: str | None = None
    dimensions: tuple[str, ...] = ()
    description: str | None = None


class CatalogSnapshot(_Frozen):
    source_kind: str
    tables: tuple[TableMeta, ...]
    lineage: LineageGraph
    policies: tuple[ExternalPolicy, ...]
    metrics: list[MetricDefinition]

    @property
    def snapshot_hash(self) -> str:
        """Deterministic sha256 of the canonicalized snapshot content.

        Drift detection compares two snapshot_hashes. Must be stable across
        equivalent inputs (sorted-by-external_id / by-edge / by-name).
        """
        tables_sorted = sorted(self.tables, key=lambda t: t.external_id)
        edges_sorted = sorted(self.lineage.edges, key=lambda e: (e.upstream, e.downstream))
        policies_sorted = sorted(self.policies, key=lambda p: p.name)
        metrics_sorted = sorted(self.metrics, key=lambda m: m.name)

        payload = {
            "source_kind": self.source_kind,
            "tables": [t.model_dump() for t in tables_sorted],
            "edges": [e.model_dump() for e in edges_sorted],
            "policies": [p.model_dump() for p in policies_sorted],
            "metrics": [m.model_dump() for m in metrics_sorted],
        }
        canonical = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()


class CatalogDelta(_Frozen):
    """Differential between two CatalogSnapshots — emitted by drift detection."""
    added_table_ids: tuple[str, ...] = ()
    removed_table_ids: tuple[str, ...] = ()
    changed_table_ids: tuple[str, ...] = ()
    added_edges: tuple[LineageEdge, ...] = ()
    removed_edges: tuple[LineageEdge, ...] = ()
