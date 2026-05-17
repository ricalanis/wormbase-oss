"""L8 cross-source entity stitching — Protocol + dataclasses + stitch-id hash.

Surfaces:

  * :data:`EntityKind` — strict 8-value :class:`typing.Literal` covering
    the canonical entity classes the L8 strategy bank can bridge across
    sources. Mirrors
    :attr:`wormbase_ledger.entries.EntityKind` exactly — adding a value
    requires a matching additive ledger migration + doctrine review (the
    8-value enum is fixed by spec §4.2).
  * :class:`ProposedEntityStitch` — strategy output dataclass; folds 1:1
    onto an ``entity_stitch_proposed`` ledger entry.
  * :class:`EntityStitchStrategy` — the runtime :class:`typing.Protocol`
    every strategy + the composite implements. Optional-Effect Injection
    compatible (the composite accepts ``None`` for any strategy slot).
  * :func:`make_stitch_id` — deterministic SHA-256 hash for the canonical
    pair of ``(source_id, table_id, column)`` triples; **order-
    independent** (the two endpoints are sorted lex before hashing so
    ``A↔B`` and ``B↔A`` collide on one ``stitch_id``).

Structurally mirrors :mod:`wormbase_agent_gateway.lineage.protocol`,
:mod:`wormbase_agent_gateway.quality.protocol`,
:mod:`wormbase_agent_gateway.schema_impact.protocol`,
:mod:`wormbase_agent_gateway.semantic_type.protocol`, and
:mod:`wormbase_agent_gateway.column_classification.protocol`. Unlike
L4/L6, L8 does NOT introduce a new cross-axis read Protocol — the
NameMatch strategy reuses L6's
:class:`wormbase_agent_gateway.column_classification.ConfirmedSemanticTypeReader`
(the same Protocol L6 owns); the SampleOverlap strategy reuses L7's
:class:`wormbase_agent_gateway.lineage.SamplerProtocol`. **Second
consumer of L6's cross-axis Protocol** — validates the
consumer-owned-Protocol pattern is general (L6 is the only producer of
confirmed semantic-type signal; multiple downstream axes can read it
through the same Protocol).

Doctrine: Optional-Effect Injection case 14 — sixth lake-side axis
built on top of :class:`wormbase_agent_gateway.lake_loop.LakeLoopComposite`
**from day one** (after L5's case 12 and L6's case 13). Validates that
the shared composite generic continues to pay off for new consumers —
the composite is ~15 LOC of factory code instead of ~250 LOC of a
duplicated composite class. Third from-day-one consumer.

The cross-axis pattern this module participates in (3rd cross-axis
chain after L4→L3 and L6→L5):

  1. The **consuming axis** (L8) reads through a Protocol the **producing
     axis** owns or defined. The L6 :class:`ConfirmedSemanticTypeReader`
     is owned by L6; L8 imports the symbol but does NOT re-declare it.
     This keeps L8 zero-cost-on-the-producer for any cross-axis additions.
  2. The **record dataclass** L6 exposes
     (:class:`ConfirmedSemanticTypeRecord`) is the minimum-coupling
     projection — L8 uses the existing 4-field shape unchanged.
  3. **Adapter responsibility** for the cross-axis read remains with
     Sub-wave C wiring (the ``LedgerConfirmedSemanticTypeReader`` impl
     that L6 already ships). No new adapter is required for L8.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "EntityKind",
    "EntityStitchStrategy",
    "ProposedEntityStitch",
    "make_stitch_id",
]


EntityKind = Literal[
    "person",
    "organization",
    "transaction",
    "product",
    "event",
    "location",
    "session",
    "other",
]
"""The 8 canonical entity classes the L8 strategy bank can stitch across sources.

Mirrors :data:`wormbase_ledger.entries.EntityKind` exactly. Adding a
value requires:

  1. An additive ledger migration extending the payload's Literal.
  2. A matching addition here.
  3. Doctrine review — semantic drift in the enum is hard to reverse
     once strategies start emitting against new values.

``other`` is the catch-all for entities outside the named seven (e.g.
``contract``, ``incident``, ``asset`` — promotable to named kinds via
additive migration once we see cross-source demand).
"""


@dataclass(frozen=True)
class ProposedEntityStitch:
    """A candidate cross-source entity-stitch proposal from an L8 strategy.

    Designed to fold one-to-one onto an ``entity_stitch_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.EntityStitchProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedEntityStitch`.

    Fields:

      * ``stitch_id`` — deterministic, **order-independent** hash of the
        canonical pair of ``(source_id, table_id, column)`` triples.
        Same logical pair (in either order) → same id. See
        :func:`make_stitch_id`.
      * ``src_source_id_a`` / ``src_table_a`` / ``src_column_a`` — the
        "first" endpoint's source/table/column identifiers. Note the
        a/b ordering of the dataclass is **not** the canonical order —
        ``make_stitch_id`` canonicalises internally so a/b ordering of
        the dataclass fields is informational only.
      * ``src_source_id_b`` / ``src_table_b`` / ``src_column_b`` — the
        "second" endpoint's source/table/column identifiers.
      * ``upstream_semantic_type_id`` — cross-axis link back to L5's
        ``projection_semantic_types.type_id`` when the proposing
        strategy consulted a confirmed semantic type (via the reused
        L6 :class:`ConfirmedSemanticTypeReader` Protocol). ``None`` for
        strategies that don't read L5. The /lake/entity-stitch surface
        renders a "view L5 semantic type →" link when this is set.
      * ``entity_kind`` — one of :data:`EntityKind` (the 8-value
        Literal).
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary.
      * ``strategy`` — open-enum identifier (``"name_match"`` |
        ``"sample_overlap"`` | ``"schema_shape"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/entity-stitch`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g. ``{"sample_overlap_pct": 0.87,
        "endpoints_sampled": 200}``).
    """

    stitch_id: str
    src_source_id_a: str
    src_table_a: str
    src_column_a: str
    src_source_id_b: str
    src_table_b: str
    src_column_b: str
    upstream_semantic_type_id: str | None
    entity_kind: EntityKind
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class EntityStitchStrategy(Protocol):
    """Proposes candidate cross-source entity stitches for a pair of columns.

    Composable via Optional-Effect Injection (doctrine case 14). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter (see the composite metrics
    surface in :mod:`.composite`).

    All implementations are async + non-mutating; calling
    :meth:`propose` twice on the same inputs returns the same outputs
    modulo set semantics (replay stability).

    The propose signature accepts two columns — each as a dict of
    ``{"source_id", "table_id", "column"}`` — because the enclosing
    enumeration (in the Compounding factory's gather_fn) walks all
    cross-source pairs and feeds each pair to every wired strategy.
    Strategies are pair-scoped, not table-scoped, so the strategy logic
    is purely about the relationship between the two endpoints.
    """

    name: str  # strategy identifier (``"name_match"`` etc.)

    async def propose(
        self,
        *,
        company_id: UUID,
        column_a: dict,
        column_b: dict,
    ) -> list[ProposedEntityStitch]:
        """Return the proposed cross-source stitches for ``(column_a, column_b)``.

        ``column_a`` and ``column_b`` are dicts of the shape
        ``{"source_id": str, "table_id": str, "column": str}``. The
        strategy MUST treat the pair symmetrically — ``propose(a, b)``
        and ``propose(b, a)`` MUST yield the same set of stitch ids
        (the composite invokes pairs in a canonical order, but
        replay-stability tests cross-call both orderings).

        ``company_id`` is threaded through so cross-axis-reading
        strategies (e.g. :class:`.strategies.NameMatchEntityStrategy`
        when ``use_semantic_type_anchor=True``) can scope their lookups
        by tenant.
        """
        ...


def make_stitch_id(
    *,
    src_a: dict,
    src_b: dict,
) -> str:
    """Deterministic, **order-independent** hash for stitch identity.

    The hash is replay-stable: same logical pair → same ``stitch_id``
    across runs, Python interpreters, machines, AND across argument
    ordering (``make_stitch_id(a, b)`` and ``make_stitch_id(b, a)``
    return the same id). The canonicalisation sorts the two
    ``(source_id, table_id, column)`` triples lex; the smaller triple
    becomes the "first" half of the hash input.

    Uses SHA-256 over a ``"|"``-joined canonical sequence, truncated to
    32 hex chars (128 bits — collision-resistant for the stitch-proposal
    cardinality regime). Mirrors the L3 :func:`make_edge_id`, L7
    :func:`make_check_id`, L4 :func:`make_impact_id`, L5
    :func:`make_type_id`, and L6 :func:`make_classification_id` shape.

    ``src_a`` and ``src_b`` are dicts of the shape
    ``{"source_id": str, "table_id": str, "column": str}``; each value
    SHOULD be a non-empty string on a valid proposal (the ledger
    boundary enforces non-emptiness at write time).

    Note: ``confidence``, ``strategy``, ``reasoning``, and ``evidence``
    are deliberately NOT in the hash — two strategies proposing the
    same pair (in either order) MUST collide so the composite can merge
    them. This mirrors L5's :func:`make_type_id` (which omits strategy)
    and diverges from L6's :func:`make_classification_id` (which
    includes strategy) — L8's spec §4.4 wants cross-strategy merge
    behaviour, not side-by-side comparison.
    """
    parts_a = (
        str(src_a["source_id"]),
        str(src_a["table_id"]),
        str(src_a["column"]),
    )
    parts_b = (
        str(src_b["source_id"]),
        str(src_b["table_id"]),
        str(src_b["column"]),
    )
    # Canonicalise: sort the two triples lex so a/b ordering is
    # irrelevant at hash time.
    canonical = sorted([parts_a, parts_b])
    flat = "|".join(part for triple in canonical for part in triple)
    return hashlib.sha256(flat.encode("utf-8")).hexdigest()[:32]
