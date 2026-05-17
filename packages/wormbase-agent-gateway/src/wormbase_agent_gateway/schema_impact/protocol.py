"""L4 schema-evolution-impact — Protocol + dataclasses + impact-id hash.

Surfaces:

  * :data:`ChangeKind` — strict 3-value :class:`typing.Literal` covering
    the upstream schema-change taxonomy.
  * :data:`ImpactKind` — strict 5-value :class:`typing.Literal` covering
    the downstream consequence taxonomy.
  * :class:`ColumnChange` — per-column diff between two catalog
    snapshots; strategy input.
  * :class:`LineageEdgeRecord` — cross-axis projection of L3's
    confirmed lineage edges; the minimum-coupling field set L4 needs to
    propagate impacts.
  * :class:`LineageEdgeReader` — **NEW cross-axis Protocol**. The first
    instance of an axis reading another axis's projection. Future
    cross-axis chains follow this template (minimum-coupling Protocol +
    record dataclass on the consuming side).
  * :class:`ProposedImpact` — strategy output dataclass; folds 1:1 onto
    a ``schema_impact_proposed`` ledger entry.
  * :class:`SchemaImpactService` — the runtime :class:`typing.Protocol`
    every strategy + the composite implements. Optional-Effect Injection
    compatible (the composite accepts ``None`` for any strategy slot).
  * :func:`make_impact_id` — deterministic SHA-256 hash of the canonical
    impact tuple. Replay-stable across runs; same logical impact → same
    ``impact_id``.

Structurally mirrors :mod:`wormbase_agent_gateway.lineage.protocol` and
:mod:`wormbase_agent_gateway.quality.protocol`, but adds the cross-axis
read pattern: strategies inject a :class:`LineageEdgeReader` to consume
L3's confirmed edges. The Protocol is deliberately scoped to the
``(src_column → downstream)`` lookup pattern L4 needs — minimum
coupling, no broad "lineage repository" surface.

The cross-axis pattern this module establishes:

  1. The **consuming axis** owns the Protocol (here L4 owns
     :class:`LineageEdgeReader`). The producing axis (L3) is unaware
     of the consumer; the Protocol is fulfilled by an adapter that
     reads L3's projection.
  2. The **record dataclass** exposes the minimum fields the consumer
     needs (here :class:`LineageEdgeRecord`). Sub-setting the producer's
     full payload keeps coupling tight — adding a column to the
     producer's projection does NOT touch the consumer's Protocol.
  3. The **Protocol surface** is scoped to the consumer's actual query
     pattern. Here L4's only need is ``(source_id, src_column) →
     [confirmed edges]``, so the Protocol has exactly one method. Future
     consumers add their own methods; the existing Protocol stays stable.

This is the first cross-axis read in the lake-side compounding stack;
expect L5, L6 etc to follow the same pattern (own Protocol, own record,
adapter in worm-core wiring).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "ChangeKind",
    "ColumnChange",
    "ImpactKind",
    "LineageEdgeReader",
    "LineageEdgeRecord",
    "ProposedImpact",
    "SchemaImpactService",
    "make_impact_id",
]


ChangeKind = Literal["column_added", "column_dropped", "column_type_changed"]
"""The 3 upstream schema-change classes L4 reasons over.

Mirrors :attr:`wormbase_ledger.entries.SchemaImpactProposedPayload.change_kind`
exactly. A new change class requires an additive ledger migration AND
a matching change here — the two stay in lockstep.
"""


ImpactKind = Literal[
    "tgt_column_orphaned",
    "tgt_column_type_mismatch",
    "tgt_column_unaware",
    "dbt_test_breakage",
    "type_coercion_required",
]
"""The 5 downstream-consequence classes L4 can propose.

Mirrors :attr:`wormbase_ledger.entries.SchemaImpactProposedPayload.impact_kind`
exactly.

Mapping from upstream ``change_kind`` to typical downstream
``impact_kind`` (see :mod:`.strategies` for details):

  * ``column_dropped`` → ``tgt_column_orphaned`` (high confidence —
    drop is unambiguous)
  * ``column_type_changed`` → ``tgt_column_type_mismatch`` (downstream
    may need coercion) AND ``type_coercion_required`` (suggested CAST)
  * ``column_added`` → ``tgt_column_unaware`` (lower confidence —
    addition rarely breaks anything, but a downstream may want to
    consume it)
  * ANY change on a column with dbt tests → ``dbt_test_breakage`` (the
    DbtTestImpactStrategy emits this on configured upstream)
"""


@dataclass(frozen=True)
class ColumnChange:
    """Per-column diff between two catalog snapshots.

    Strategy input. Produced by L4's gather_fn (Sub-wave B factory)
    after diffing the triggering ``external_catalog_imported`` snapshot
    against the prior snapshot for the same source.

    Fields:

      * ``src_table`` — canonical
        ``"<source_id>.<schema>.<table>"`` identifier (same shape as
        Wave-1's wormbase-catalog-mirror table-id grammar).
      * ``src_column`` — column name on the source side.
      * ``change_kind`` — one of :data:`ChangeKind`.
      * ``old_type`` — column type in the prior snapshot;
        ``None`` for ``column_added``.
      * ``new_type`` — column type in the triggering snapshot;
        ``None`` for ``column_dropped``.
    """

    src_table: str
    src_column: str
    change_kind: ChangeKind
    old_type: str | None
    new_type: str | None


@dataclass(frozen=True)
class LineageEdgeRecord:
    """Cross-axis projection of L3's confirmed lineage edges.

    Exposes the minimum fields L4's impact propagation needs;
    deliberately a subset of L3's full payload (see
    :class:`wormbase_agent_gateway.lineage.InferredEdge` for the full
    L3 record).

    Coupling-minimization principle: adding a field to L3's full edge
    payload should NOT force a change here. The consumer-owned-Protocol
    pattern (this module) trades zero-coupling-cost-on-the-producer for
    a small adapter surface on the worm-core wiring side.

    Fields:

      * ``edge_id`` — L3's deterministic edge identity (see
        :func:`wormbase_agent_gateway.lineage.make_edge_id`). L4 threads
        this through onto :attr:`ProposedImpact.upstream_lineage_edge_id`
        so the impact entry links back to the originating L3 edge.
      * ``src_table_id`` / ``src_column`` / ``tgt_table_id`` /
        ``tgt_column`` — the L3-confirmed edge endpoints. L4's
        :class:`.strategies.LineageEdgeImpactStrategy` proposes one
        impact per (changed_column, downstream-edge) pair.
      * ``confidence`` — L3's edge confidence in [0.0, 1.0]. L4's
        impact confidence is computed as ``edge.confidence × impact_factor``
        (see :mod:`.strategies` for the per-(change_kind, strategy)
        factors).
      * ``strategy`` — L3 strategy that produced the edge
        (``"dbt_manifest"`` | ``"naming_heuristic"`` |
        ``"sample_overlap"`` | future). L4 may filter by strategy
        (e.g. only propagate from dbt-manifest edges to keep
        false-positive rate low).
    """

    edge_id: str
    src_table_id: str
    src_column: str
    tgt_table_id: str
    tgt_column: str
    confidence: float
    strategy: str


@runtime_checkable
class LineageEdgeReader(Protocol):
    """**Cross-axis read Protocol — first instance.**

    Exposes L3's confirmed lineage edges to other axes (L4 today,
    future L5+ as needed). The Protocol is intentionally scoped to the
    ``(source_id, src_column) → [confirmed edges]`` lookup pattern that
    L4's :class:`.strategies.LineageEdgeImpactStrategy` needs;
    additional methods join the Protocol only when an axis genuinely
    needs them.

    This is the **canonical cross-axis-read pattern**: future cross-
    axis Protocols (e.g. quality-check signal → schema-impact, or
    schema-impact → process-extractor) follow the same template:

      * The **consuming axis** owns the Protocol.
      * The Protocol declares the minimum query surface, not a broad
        repository.
      * A :class:`@dataclass` record (see :class:`LineageEdgeRecord`)
        exposes only the fields the consumer needs.
      * Worm-core wiring provides the concrete impl that reads the
        producer's projection (here ``projection_lineage_edges``).

    Tenant isolation rides on ``company_id`` — every call carries the
    tenant scope and the impl MUST honor it. There is no global
    "all-tenants" read path through this Protocol; downstream auditing
    relies on the scoped read.

    Replay-stability: implementations MUST be order-deterministic for
    a given ``(company_id, source_id, src_column)`` so re-running the
    same impact discovery yields the same proposed edges.
    """

    async def list_confirmed_edges_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id: UUID,
    ) -> list[LineageEdgeRecord]:
        """Return the L3-confirmed edges originating at ``(source_id, src_column)``.

        Filter contract:

          * State = "confirmed" on
            :class:`wormbase_ledger.SchemaImpactConfirmedPayload`'s sister
            projection ``projection_lineage_edges``.
          * Source-column match: ``edges WHERE src_column = <src_column>
            AND src_table_id LIKE "<source_id>.%"``.

        Edges where ``src_column`` is ``None`` (whole-table edges from
        L3's dbt-manifest strategy) are NOT returned — column-grain
        propagation is the only thing L4 reasons over today.

        Returns the empty list when no confirmed edges match; callers
        treat this as a no-op (the strategy proposes no impacts).
        """
        ...


@dataclass(frozen=True)
class ProposedImpact:
    """A candidate downstream impact from an L4 strategy.

    Designed to fold one-to-one onto a ``schema_impact_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.SchemaImpactProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedImpact`.

    Fields:

      * ``impact_id`` — deterministic hash of
        ``(source_id, src_table, src_column, change_kind, tgt_table_id,
        tgt_column)``. Same logical impact → same id. See
        :func:`make_impact_id`.
      * ``source_id`` — the L4-triggering source (the source whose
        catalog snapshot just changed).
      * ``src_table`` / ``src_column`` — the changed column on the
        source side.
      * ``change_kind`` — one of :data:`ChangeKind`.
      * ``impact_kind`` — one of :data:`ImpactKind`.
      * ``tgt_table_id`` / ``tgt_column`` — the downstream table/column
        affected by the change.
      * ``upstream_lineage_edge_id`` — the L3 edge that surfaced this
        impact, or ``None`` for non-edge-driven strategies (e.g.
        :class:`.strategies.TypeCoercionImpactStrategy` may emit on
        bare type metadata without an L3 edge).
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary (see
        :class:`wormbase_ledger.entries.SchemaImpactProposedPayload`).
      * ``strategy`` — open-enum identifier (``"lineage_edge"`` |
        ``"dbt_test"`` | ``"type_coercion"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/schema-impact`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g. ``{"upstream_change_seq": 1234,
        "lineage_edge_strategy": "dbt_manifest"}``).
    """

    impact_id: str
    source_id: str
    src_table: str
    src_column: str
    change_kind: ChangeKind
    impact_kind: ImpactKind
    tgt_table_id: str
    tgt_column: str
    upstream_lineage_edge_id: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class SchemaImpactService(Protocol):
    """Proposes candidate downstream impacts for a column-level schema change.

    Composable via Optional-Effect Injection (doctrine case 11). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter (see
    :class:`.composite.CompositeSchemaImpactService.metrics`).

    All implementations are async + non-mutating; calling
    :meth:`propose_impacts` twice on the same inputs returns the same
    outputs modulo set semantics (replay stability).
    """

    name: str  # strategy identifier (``"lineage_edge"`` etc.)

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: UUID,
    ) -> list[ProposedImpact]:
        """Return the proposed impacts for ``change`` on ``(source_id, src_table)``.

        ``company_id`` is threaded through so cross-axis-reading
        strategies (e.g. :class:`.strategies.LineageEdgeImpactStrategy`)
        can scope their lookups by tenant.
        """
        ...


def make_impact_id(
    *,
    source_id: str,
    src_table: str,
    src_column: str,
    change_kind: str,
    tgt_table_id: str,
    tgt_column: str,
) -> str:
    """Deterministic hash for impact identity.

    The hash is replay-stable: same logical impact → same ``impact_id``
    across runs, Python interpreters, machines. This is the dedup key
    for both the composite (merging multi-strategy proposals) and the
    projection fold (collapsing re-proposals onto one row).

    Uses SHA-256 over a ``"|"``-joined canonical tuple, truncated to 32
    hex chars (128 bits — collision-resistant for the impact
    cardinality regime). Mirrors the L3 :func:`make_edge_id` and L7
    :func:`make_check_id` shape.

    All six tuple components are non-empty strings on a valid impact;
    callers SHOULD enforce non-emptiness before hashing (the ledger
    boundary enforces it at write time).
    """
    parts = [
        source_id,
        src_table,
        src_column,
        change_kind,
        tgt_table_id,
        tgt_column,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
