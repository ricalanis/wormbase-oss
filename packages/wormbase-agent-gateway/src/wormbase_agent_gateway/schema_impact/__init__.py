"""L4 lake-side schema-evolution-impact discovery subpackage.

Public surface for the L4 Compounding axis:

  * :class:`SchemaImpactService` — Protocol every strategy + the
    composite implements.
  * :class:`ProposedImpact` — strategy output dataclass; folds 1:1 onto
    a ``schema_impact_proposed`` ledger entry.
  * :class:`ColumnChange` — per-column diff between two catalog
    snapshots; strategy input.
  * :class:`LineageEdgeRecord` — minimum-coupling projection of L3's
    confirmed edges; the value object the cross-axis Protocol returns.
  * :class:`LineageEdgeReader` — **NEW cross-axis Protocol** that
    exposes L3's confirmed lineage edges to L4 (and future consumers).
    First instance of an axis reading another axis's projection.
  * :data:`ChangeKind` — strict 3-value Literal covering the upstream
    schema-change taxonomy.
  * :data:`ImpactKind` — strict 5-value Literal covering the downstream
    consequence taxonomy.
  * :func:`make_impact_id` — deterministic SHA-256 hash for impact
    identity.
  * :class:`LineageEdgeImpactStrategy` — cross-axis-reading strategy
    that propagates impacts via L3's confirmed edges.
  * :class:`DbtTestImpactStrategy` — propagates impacts via existing
    dbt tests on the changed column; reuses L7's
    :class:`DbtTestReader` Protocol.
  * :class:`TypeCoercionImpactStrategy` — reasons over column type
    transitions; optionally cross-axis-reads via the lineage edge
    reader.
  * :class:`CompositeSchemaImpactService` — Optional-Effect Injection
    composition over the 3 strategies (doctrine case 11).

Sub-wave B (2026-06-02) ships these. Sub-wave C wires them through
the boot path (with the concrete :class:`LedgerLineageEdgeReader`);
Sub-wave D ships the admin ``/lake/schema-impact`` dashboard surface.
"""
from __future__ import annotations

from .composite import CompositeSchemaImpactService
from .protocol import (
    ChangeKind,
    ColumnChange,
    ImpactKind,
    LineageEdgeReader,
    LineageEdgeRecord,
    ProposedImpact,
    SchemaImpactService,
    make_impact_id,
)
from .strategies import (
    AcknowledgedDriftImpactStrategy,
    DbtTestImpactStrategy,
    GovernanceClassificationImpactStrategy,
    LineageEdgeImpactStrategy,
    SemanticTypeImpactStrategy,
    TypeCoercionImpactStrategy,
)

__all__ = [
    "AcknowledgedDriftImpactStrategy",
    "ChangeKind",
    "ColumnChange",
    "CompositeSchemaImpactService",
    "DbtTestImpactStrategy",
    "GovernanceClassificationImpactStrategy",
    "ImpactKind",
    "LineageEdgeImpactStrategy",
    "LineageEdgeReader",
    "LineageEdgeRecord",
    "ProposedImpact",
    "SchemaImpactService",
    "SemanticTypeImpactStrategy",
    "TypeCoercionImpactStrategy",
    "make_impact_id",
]
