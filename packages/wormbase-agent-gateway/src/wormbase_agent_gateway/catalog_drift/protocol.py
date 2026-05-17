"""L2 catalog-drift detection — Protocol + dataclasses + Reader Protocol.

Surfaces:

  * :class:`ProposedCatalogDrift` — strategy output dataclass; folds
    1:1 onto a ``catalog_drift_proposed`` ledger entry.
  * :class:`CatalogDriftStrategy` — the runtime
    :class:`typing.Protocol` every strategy + the composite implements.
    Optional-Effect Injection compatible (the composite accepts ``None``
    for any strategy slot).
  * :class:`CatalogSnapshotReader` — lightweight Reader Protocol over
    the ``external_catalog_imported`` ledger entry kind. Returns
    :class:`CatalogSnapshot` records (current + baseline) reconstructed
    per ``(company_id, source_id)`` so strategies can diff structure.
  * :class:`CatalogSnapshot` + :class:`CatalogTable` +
    :class:`CatalogColumn` — minimum projection of an external catalog
    snapshot. ``CatalogTable.columns`` is empty today (per Sub-wave A
    payload-shape verification — the ``external_catalog_imported``
    entry carries ``added_table_ids`` / ``removed_table_ids`` but no
    per-column structure yet); the dataclass is forward-compatible
    for richer-diff emitters in later waves.
  * :func:`make_drift_id` import re-export from :mod:`wormbase_ledger`
    so callers and tests see a single deterministic-hash entry point.

Structurally mirrors :mod:`wormbase_agent_gateway.source_candidates.protocol`
(L1) for the Reader-Protocol pattern. L1's three Readers consume
first-class platform projections; L2's single Reader consumes the
catalog-mirror substrate (``external_catalog_imported`` entries). Per
spec §4.6 doctrine clarification, this is the **platform-reader**
category — NOT a peer-axis cross-axis chain. The producer
(catalog-mirror) is substrate, not a Compounding loop. Cross-axis
chain count stays at **3** (L4→L3, L6→L5, L8→L5).

Doctrine: Optional-Effect Injection case 16 — **fifth lake-side axis
built on top of** :class:`wormbase_agent_gateway.lake_loop.LakeLoopComposite`
**from day one** (after L5 case 12, L6 case 13, L8 case 14, L1 case 15).
Continues the zero-friction streak — the composite is ~10-13 LOC of
factory code instead of ~250 LOC of a duplicated composite class.

L2 is the **8th lake-side axis** overall (the FINAL planned axis in
this generation; L-axis family completes at 24 of 30 with this
ship — L2 ships 3 kinds, lifting registry from 129 → 132).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from wormbase_ledger import make_drift_id

__all__ = [
    "AcknowledgedDriftReader",
    "AcknowledgedDriftRecord",
    "CatalogColumn",
    "CatalogDriftStrategy",
    "CatalogSnapshot",
    "CatalogSnapshotReader",
    "CatalogTable",
    "ProposedCatalogDrift",
    "make_drift_id",
]


# ---------------------------------------------------------------------------
# Proposal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedCatalogDrift:
    """A proposed catalog-drift event from an L2 detection strategy.

    Designed to fold one-to-one onto a ``catalog_drift_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.CatalogDriftProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedCatalogDrift`.

    Fields:

      * ``drift_id`` — deterministic SHA-256 prefix hash of
        ``(source_id, table_id, column, drift_kind, before, after)``
        minted via :func:`make_drift_id`. Same drift detected twice
        (same strategy on the same snapshot pair) → same hash → folds
        onto the same projection row (natural dedup via the composite
        PK ``(company_id, drift_id)``).
      * ``source_id`` — opaque source identifier (per L3 source
        grammar). Required.
      * ``table_id`` — fully-qualified table id where the drift was
        observed. Required for ALL drift_kinds.
      * ``column`` — column name when ``drift_kind`` is ``column_*``;
        ``None`` for ``table_*`` drifts (the payload validator enforces
        the column / drift_kind coherence invariant).
      * ``drift_kind`` — one of the 5 ``CatalogDriftKind`` Literal
        values: ``table_added`` / ``table_removed`` / ``column_added``
        / ``column_removed`` / ``column_type_changed``.
      * ``before`` — structured dict snapshot of the prior attribute
        state. ``None`` for ``*_added`` drifts (no prior value). Strategy-
        specific shape: TableSet emits ``{"table_id": ...}``; ColumnSet
        emits ``{"name": ...}``; ColumnType emits ``{"type": "..."}``.
      * ``after`` — structured dict snapshot of the new attribute state.
        ``None`` for ``*_removed`` drifts (no current value). Same
        strategy-specific shape as ``before``.
      * ``strategy`` — open-enum identifier
        (``"table_set"`` | ``"column_set"`` | ``"column_type"`` |
        future plug-ins).
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary. L2 strategies emit at 0.90 (TableSet)
        / 0.85 (ColumnSet) / 0.80 (ColumnType) — high confidence because
        catalog-diff signal is structural, not statistical.
      * ``reasoning`` — human-readable explanation surfaced on the
        admin drift-detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (TableSet carries
        ``{"before_tables": [...], "after_tables": [...]}``;
        ColumnSet carries ``{"before_columns": [...], "after_columns":
        [...]}``; ColumnType carries ``{"before_type": "...",
        "after_type": "..."}``).
    """

    drift_id: str
    source_id: str
    table_id: str
    column: str | None
    drift_kind: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    strategy: str
    confidence: float
    reasoning: str
    evidence: dict[str, Any]


# ---------------------------------------------------------------------------
# Strategy Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CatalogDriftStrategy(Protocol):
    """Proposes catalog-drift events from a (current, baseline) snapshot pair.

    Composable via Optional-Effect Injection (doctrine case 16). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter.

    All implementations are async + non-mutating; calling
    :meth:`propose` twice on the same inputs returns the same outputs
    modulo set semantics (replay stability).

    L2 strategies are **snapshot-pair-scoped** — they diff a freshly-
    landed ``current`` snapshot against the ``baseline`` (the prior
    ``external_catalog_imported`` for the same source). The composite
    invokes them once per ``external_catalog_imported`` event, with the
    snapshot pair already reconstructed by the gather_fn via
    :class:`CatalogSnapshotReader`.
    """

    name: str  # strategy identifier (``"table_set"`` etc.)

    async def propose(
        self,
        *,
        company_id: UUID,
        current: "CatalogSnapshot",
        baseline: "CatalogSnapshot | None",
    ) -> list[ProposedCatalogDrift]:
        """Return the proposed drift events for ``(current, baseline)``.

        ``baseline`` MAY be ``None`` when ``current`` is the first
        snapshot for the source (no prior ``external_catalog_imported``
        landed yet). Most strategies treat this case as "no drift to
        report" and return ``[]`` (the honest stub posture — first
        snapshot is the baseline, not a drift).

        Strategies MAY return an empty list when upstream signal is
        missing (e.g. ColumnSet / ColumnType when
        ``current.tables[*].columns == ()`` per today's payload-shape
        limitation). The composite is designed for this: a wired
        strategy returning ``[]`` does NOT increment the ``no_op``
        counter (that's reserved for the all-None Optional-Effect-
        absent path).
        """
        ...


# ---------------------------------------------------------------------------
# CatalogSnapshot dataclasses — minimum projection for diffing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogColumn:
    """Minimum projection of a column from a catalog snapshot.

    Fields:

      * ``name`` — column name (e.g. ``"customer_id"``, ``"created_at"``).
      * ``type`` — type string (e.g. ``"varchar(255)"``, ``"timestamp"``,
        ``"bigint"``). ``None`` when the upstream catalog metadata
        does not surface type info (Sub-wave A handoff confirmed
        ``external_catalog_imported`` carries only table ids today).

    Lightweight on purpose — L2's three strategies only need (name,
    type) to compute column-level diffs. Sub-wave A handoff concern
    #3: the ``type`` field accepts dict / str / None at the
    :class:`ProposedCatalogDrift.before` / ``after`` layer; here
    on the snapshot side it's a flat string (or None) because
    upstream catalog descriptors typically render the type as
    a single canonical token.
    """

    name: str
    type: str | None = None


@dataclass(frozen=True)
class CatalogTable:
    """Minimum projection of a table from a catalog snapshot.

    Fields:

      * ``table_id`` — fully-qualified table id (per L3 source grammar:
        ``<source_id>.<schema>.<table>``).
      * ``columns`` — tuple of :class:`CatalogColumn` records. **Empty
        today** per the ``external_catalog_imported`` payload-shape
        limitation (Sub-wave A handoff: the entry carries
        ``added_table_ids`` / ``removed_table_ids`` tuples but no
        per-table column structure). Forward-compatible: when richer
        emitters land, the same dataclass shape carries the columns
        without any L2-side schema change.

    L2's :class:`TableSetDriftStrategy` operates productively today
    on the ``table_id`` field alone; :class:`ColumnSetDriftStrategy`
    and :class:`ColumnTypeDriftStrategy` honest-stub when
    ``columns == ()`` and become productive automatically once
    upstream provides per-column structure.
    """

    table_id: str
    columns: tuple[CatalogColumn, ...] = ()


@dataclass(frozen=True)
class CatalogSnapshot:
    """Reconstructed external-catalog snapshot at a point in time.

    A :class:`CatalogSnapshotReader` builds these from
    ``external_catalog_imported`` ledger entries. The current snapshot
    is the most-recently-landed entry; the baseline is the
    previously-landed entry for the same ``(company_id, source_id)``.

    Fields:

      * ``source_id`` — opaque source identifier.
      * ``as_of`` — timestamp the snapshot was imported (the
        ``external_catalog_imported`` execute entry's ledger
        timestamp). UTC, tz-aware.
      * ``tables`` — tuple of :class:`CatalogTable` records present at
        ``as_of``. Empty tuple when the snapshot has no tables yet
        (e.g. an empty catalog at first import).
    """

    source_id: str
    as_of: datetime
    tables: tuple[CatalogTable, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# CatalogSnapshotReader Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CatalogSnapshotReader(Protocol):
    """Reads ``external_catalog_imported`` entries to reconstruct snapshots.

    Consumed by the L2 catalog-drift Compounding axis's gather_fn:
    when an ``external_catalog_imported`` entry lands, the gather_fn
    asks the reader for ``(current, baseline)`` for the affected
    ``(company_id, source_id)``.

    **NOT a cross-axis chain** — ``external_catalog_imported`` is a
    first-class catalog-mirror substrate entry kind (folded from
    catalog-mirror's W5a Reactivities), not a peer lake-axis projection.
    The producer is substrate, not a Compounding loop. Per spec §4.6
    doctrine clarification, this is the **platform-reader** category;
    cross-axis chain count stays at 3.

    Implementations MUST:

      * Return ``(current, baseline)`` where ``current`` is the
        most-recent ``external_catalog_imported`` for the source
        (typically the one that just landed and triggered the
        Reactivity), and ``baseline`` is the second-most-recent (or
        ``None`` when only one snapshot exists).
      * Be tenant-scoped: only return entries for the given
        ``company_id``.
      * Be deterministic: same ledger state → same snapshots.
    """

    async def read_current_and_baseline(
        self,
        *,
        company_id: UUID,
        source_id: str,
    ) -> tuple[CatalogSnapshot, CatalogSnapshot | None]:
        """Return ``(current, baseline)`` snapshots for the source.

        ``current`` is the most-recently-landed snapshot; ``baseline``
        is the prior snapshot (``None`` when this is the first
        snapshot for the source).

        Implementations SHOULD raise a domain-specific error (or
        return ``(CatalogSnapshot(source_id, as_of, ()), None)`` if
        graceful degradation is preferred) when the source has no
        ``external_catalog_imported`` entries at all — the gather_fn
        treats either signal as "no drift to compute."
        """
        ...


# ---------------------------------------------------------------------------
# AcknowledgedDriftReader Protocol — L4↦L2 cross-axis chain (forward arc)
#
# Producer-side cross-axis Protocol. The first PRODUCER-side Protocol on L2
# (CatalogSnapshotReader is a platform-substrate reader, not a peer-axis
# cross-axis chain). Mirrors L6's :class:`ConfirmedClassificationReader`
# pattern: the data-domain owner exposes the read surface; downstream axes
# import it directly.
#
# L4's :class:`AcknowledgedDriftImpactStrategy` consumes this to elevate
# schema-evolution impact severity when a change touches a column with an
# acknowledged drift. Future consumers (e.g. a stability-monitor axis)
# can import the same Protocol; the read surface stays stable.
#
# ``AcknowledgedDriftRecord`` exposes the minimum coupling field set — the
# joined fold of ``catalog_drift_proposed`` (source/table/column/drift_kind/
# before/after) AND ``catalog_drift_acknowledged`` (acknowledged_at /
# acknowledged_by_person_id), filtered to drifts whose final state is
# acknowledged. Rejected drifts are NOT exposed; a re-acknowledged drift
# emits a new ledger entry and IS exposed (last-write-wins per the
# projection-fold semantics in v028).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcknowledgedDriftRecord:
    """Cross-axis projection of an L2 acknowledged catalog drift.

    Exposes the minimum fields a downstream consumer (today L4's
    :class:`AcknowledgedDriftImpactStrategy`) needs; deliberately a
    subset of the joined :class:`CatalogDriftProposedPayload` +
    :class:`CatalogDriftAcknowledgedPayload` view.

    Coupling-minimization principle (mirrors L6's
    :class:`ConfirmedClassificationRecord` + L4's
    :class:`LineageEdgeRecord`): adding a field to L2's full drift
    payload should NOT force a change here. Producer-side ownership
    sits on L2 because the
    :data:`wormbase_ledger.entries.CatalogDriftKind` taxonomy lives on
    L2; placing the Reader Protocol on a consumer's side would force
    that consumer to import L2's taxonomy.

    Fields:

      * ``drift_id`` — L2's deterministic drift identity (per
        :func:`make_drift_id`). Threaded onto the proposed impact's
        ``evidence["upstream_drift_id"]`` so the impact row links back
        to the originating L2 acknowledgement (the cross-axis chain
        that powers the "↪ view L2 acknowledged drift" link on the
        future /lake/schema-impact rows).
      * ``source_id`` — the source the drift was observed on; matches
        the source_id field on the original proposal.
      * ``table_id`` — fully-qualified table id where the drift was
        observed. Non-empty for all drift_kinds.
      * ``column`` — column name when ``drift_kind`` is ``column_*``;
        ``None`` for ``table_added`` / ``table_removed`` (table-level
        drifts have no column). The payload validator enforces the
        coherence invariant at write time.
      * ``drift_kind`` — one of the 5
        :data:`wormbase_ledger.entries.CatalogDriftKind` values.
        Surfaced to the consumer so it can route severity per-kind
        if it wants (today's L4 strategy treats all kinds the same).
      * ``before`` — structured dict snapshot of the prior attribute
        state. ``None`` for ``*_added`` drifts.
      * ``after`` — structured dict snapshot of the new attribute state.
        ``None`` for ``*_removed`` drifts.
      * ``acknowledged_at`` — platform clock time of the acknowledgment
        (the :class:`CatalogDriftAcknowledgedPayload` entry's ledger ts).
        Threaded for audit / "stale-acknowledgement" surfacing.
      * ``acknowledged_by_person_id`` — WormBase-internal Person UUID of
        the operator who acknowledged; threaded for audit.
    """

    drift_id: str
    source_id: str
    table_id: str
    column: str | None
    drift_kind: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    acknowledged_at: datetime
    acknowledged_by_person_id: str


@runtime_checkable
class AcknowledgedDriftReader(Protocol):
    """**L4↦L2 cross-axis read Protocol — first producer-side L2 Protocol.**

    Exposes L2's acknowledged catalog drifts (the SUBSET of proposed
    drifts whose final state is acknowledged — proposed-only drifts and
    rejected drifts are NOT exposed) to other axes. The Protocol is
    intentionally scoped to two lookup patterns:

      * Scan ALL acknowledged drifts (for tenant-level banner / counts).
      * Lookup by ``(source_id, column)`` (for L4's strategy hot path —
        per-changed-column severity elevation).

    Tenant isolation rides on ``company_id`` per call. There is no
    global "all-tenants" read path through this Protocol; downstream
    auditing relies on the scoped read.

    Replay-stability: implementations MUST be order-deterministic for
    a given ``(company_id, ...)`` so re-running the same
    acknowledged-drift-impact elevation yields the same proposed
    impacts. The canonical impl folds the ledger in oldest-first order
    and sorts records by ``drift_id`` before returning.

    This is the **first PRODUCER-side cross-axis Protocol on L2**
    (:class:`CatalogSnapshotReader` is a platform-substrate reader of
    ``external_catalog_imported`` — distinct category per spec §4.6).
    With this Protocol, L2's producer-side Protocols count goes from 1
    → 2. The L4↦L2 chain is the **7th cross-axis chain** overall and the
    **first bidirectional** chain: L4 elevates impacts on L2-
    acknowledged drifts (forward), while the L2 dashboard surfaces
    downstream-impact roll-up counts per drift row (reverse).
    """

    async def list_acknowledged_drifts(
        self,
        *,
        company_id: UUID,
    ) -> list[AcknowledgedDriftRecord]:
        """Return ALL acknowledged drifts for the tenant.

        Filter contract:

          * Final state = "acknowledged" — drifts in proposed state OR
            currently rejected are NOT returned. A drift that was
            acknowledged then later rejected is NOT returned (rejection
            wins per the projection-fold semantics). A drift that was
            rejected then re-proposed and re-acknowledged IS returned
            (last-write-wins).
          * No source / column filter — every acknowledged drift in the
            tenant is surfaced.

        Returns ``[]`` when no acknowledged drifts match.

        Order: deterministic by ``drift_id`` ascending for replay
        stability.

        Used today by:
          * /lake/catalog-drift banner ("X drifts have downstream impacts")
            — though this surface is presently optional in Wave 1.
        """
        ...

    async def list_acknowledged_drifts_for_source_column(
        self,
        source_id: str,
        src_column: str | None,
        *,
        company_id: UUID,
    ) -> list[AcknowledgedDriftRecord]:
        """Return acknowledged drifts on ``(source_id, src_column)``.

        Filter contract:

          * State = "acknowledged" (same as
            :meth:`list_acknowledged_drifts`).
          * Source match: ``source_id`` equals the drift's source_id
            field exactly.
          * Column match: when ``src_column`` is non-None, the drift's
            ``column`` field must equal it exactly (column-grain drifts
            only — table-level drifts are filtered out). When
            ``src_column`` is None, ONLY table-level drifts (drift.column
            is None) are returned.

        Returns ``[]`` when no acknowledged drifts match — callers
        treat this as a no-op (the strategy proposes no acknowledged-
        drift-elevated impacts).

        Used today by:
          * :class:`AcknowledgedDriftImpactStrategy` on L4 — proposes
            an elevated-severity impact for the changed column when an
            acknowledged drift exists on that column.
        """
        ...
