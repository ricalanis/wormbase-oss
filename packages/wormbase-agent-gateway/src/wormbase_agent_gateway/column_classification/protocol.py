"""L6 column-level governance classification — Protocol + dataclasses + classification-id hash.

Surfaces:

  * :data:`ClassificationLevel` — strict 5-value :class:`typing.Literal`
    covering the canonical governance levels (public / internal /
    confidential / pii / regulated). Mirrors
    :attr:`wormbase_ledger.entries.ColumnClassificationProposedPayload.classification_level`
    exactly — adding a value here requires a matching additive ledger
    migration AND doctrine review (the 5-value enum is fixed by spec
    §4.2).
  * :class:`ConfirmedSemanticTypeRecord` — **NEW cross-axis projection**
    of L5's confirmed semantic types. Minimum coupling — only the
    4 fields L6 needs from L5's full payload.
  * :class:`ConfirmedSemanticTypeReader` — **NEW cross-axis Protocol —
    second instance after L4's :class:`LineageEdgeReader`**. Exposes
    L5's confirmed semantic types to L6 (the cross-axis chain that
    powers the "view L5 semantic type →" link on the
    /lake/column-classification surface). Follows the canonical
    cross-axis-read template the L4 module established: consuming axis
    owns the Protocol, declares the minimum query surface, ships a
    minimum-field record dataclass on the consumer side.
  * :class:`ProposedColumnClassification` — strategy output dataclass;
    folds 1:1 onto a ``column_classification_proposed`` ledger entry.
  * :class:`ColumnClassificationStrategy` — runtime
    :class:`typing.Protocol` every strategy + the composite implements.
    Optional-Effect Injection compatible (the composite accepts ``None``
    for any strategy slot).
  * :func:`make_classification_id` — deterministic SHA-256 hash of the
    canonical ``(table_id, column, classification_level, strategy)``
    tuple. Replay-stable across runs; same logical proposal → same
    ``classification_id``. Note ``strategy`` IS part of the hash (unlike
    L5's :func:`make_type_id` which omits strategy) — L6 wants each
    strategy's per-column-per-level proposal to be its own projection
    row so the admin queue can compare strategies side-by-side. Per
    spec §4.4.

Structurally mirrors :mod:`wormbase_agent_gateway.lineage.protocol`,
:mod:`wormbase_agent_gateway.quality.protocol`,
:mod:`wormbase_agent_gateway.schema_impact.protocol`, and
:mod:`wormbase_agent_gateway.semantic_type.protocol`. Unlike L5, L6
**does** introduce a new cross-axis read Protocol — this is the **second
cross-axis chain** in the lake-side architecture (after L4→L3).

Doctrine: Optional-Effect Injection case 13 — second lake-side axis
built on top of :class:`wormbase_agent_gateway.lake_loop.LakeLoopComposite`
from day one (after L5's case 12). Validates that the shared composite
generic continues to pay off for new consumers — the composite is
~15 LOC of factory code instead of ~250 LOC of a duplicated composite
class.

The cross-axis pattern this module instantiates (second instance):

  1. The **consuming axis** owns the Protocol (here L6 owns
     :class:`ConfirmedSemanticTypeReader`). The producing axis (L5) is
     unaware of the consumer; the Protocol is fulfilled by an adapter
     that reads L5's ``projection_semantic_types`` (Sub-wave C ships
     ``LedgerConfirmedSemanticTypeReader`` mirroring L4's
     ``LedgerLineageEdgeReader``).
  2. The **record dataclass** (:class:`ConfirmedSemanticTypeRecord`)
     exposes the minimum fields the consumer needs — sub-setting L5's
     full payload keeps coupling tight. Adding a column to L5's
     projection does NOT touch this Protocol.
  3. The **Protocol surface** is scoped to L6's actual query pattern:
     ``(table_id, column, company_id) → [confirmed types]``. Exactly
     one method, exactly the shape
     :class:`.strategies.SemanticTypeClassificationStrategy` needs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

__all__ = [
    "ClassificationLevel",
    "ColumnClassificationStrategy",
    "ConfirmedClassificationReader",
    "ConfirmedClassificationRecord",
    "ConfirmedSemanticTypeReader",
    "ConfirmedSemanticTypeRecord",
    "ProposedColumnClassification",
    "make_classification_id",
]


ClassificationLevel = Literal[
    "public",
    "internal",
    "confidential",
    "pii",
    "regulated",
]
"""The 5 canonical governance classification levels.

Mirrors :attr:`wormbase_ledger.entries.ColumnClassificationProposedPayload.classification_level`
and CLAUDE.md §"Ledger-native governance" exactly. The 5-value enum is
fixed by spec §4.2; adding a value requires an additive ledger
migration + doctrine review + matching addition here.

Ordering (informational, used by the dashboard for badge coloring):

  * ``public`` — safe to expose externally
  * ``internal`` — org-internal use only
  * ``confidential`` — restricted to need-to-know (e.g. credentials)
  * ``pii`` — personally identifiable information (names, emails, etc.)
  * ``regulated`` — subject to compliance regimes (PCI, HIPAA, SOC-2,
    etc.) — typically a strict superset of ``pii`` controls
"""


@dataclass(frozen=True)
class ConfirmedSemanticTypeRecord:
    """Cross-axis projection of L5's confirmed semantic types.

    Exposes the minimum fields L6's classification propagation needs;
    deliberately a subset of L5's full
    :class:`wormbase_agent_gateway.semantic_type.ProposedSemanticType`
    payload.

    Coupling-minimization principle (mirrors L4's
    :class:`LineageEdgeRecord`): adding a field to L5's full type
    payload should NOT force a change here. The
    consumer-owned-Protocol pattern trades zero-coupling-cost-on-the-
    producer for a small adapter surface on the worm-core wiring side.

    Fields:

      * ``type_id`` — L5's deterministic type identity (see
        :func:`wormbase_agent_gateway.semantic_type.make_type_id`). L6
        threads this through onto
        :attr:`ProposedColumnClassification.upstream_semantic_type_id`
        so the classification entry links back to the originating L5
        type (the cross-axis chain that powers the "view L5 semantic
        type →" link on /lake/column-classification).
      * ``semantic_type`` — the L5-confirmed semantic type value
        (e.g. ``"pii_ssn"``, ``"email"``, ``"metric_count"``). L6's
        :class:`.strategies.SemanticTypeClassificationStrategy` maps
        each value to a classification level + base confidence.
      * ``confidence`` — L5's type confidence in [0.0, 1.0]. Carried
        through verbatim; L6's classification confidence is computed
        from the mapping table (not multiplied with L5's confidence
        today — spec §4.3 lists fixed base confidences).
      * ``strategy`` — L5 strategy that produced the type
        (``"column_name"`` | ``"value_pattern"`` | ``"distribution"`` |
        future). Surfaced for evidence; L6 does not filter on it today.
    """

    type_id: str
    semantic_type: str
    confidence: float
    strategy: str


@runtime_checkable
class ConfirmedSemanticTypeReader(Protocol):
    """**Cross-axis read Protocol — second instance.**

    Exposes L5's confirmed semantic types to L6 (and future axes that
    want classification-relevant type signal). The Protocol is
    intentionally scoped to the ``(table_id, column, company_id) →
    [confirmed types]`` lookup pattern that L6's
    :class:`.strategies.SemanticTypeClassificationStrategy` needs;
    additional methods join the Protocol only when an axis genuinely
    needs them.

    This is the **second instance** of the canonical cross-axis-read
    pattern (after L4's :class:`LineageEdgeReader`). Same shape:

      * The **consuming axis** owns the Protocol (L6 owns this; L5 is
        unaware).
      * The Protocol declares the minimum query surface, not a broad
        "semantic-types repository" — exactly one method.
      * A :class:`@dataclass` record (:class:`ConfirmedSemanticTypeRecord`)
        exposes only the fields the consumer needs.
      * Worm-core wiring (Sub-wave C) provides the concrete impl that
        reads the producer's projection (``projection_semantic_types``).
        The Sub-wave C adapter is named ``LedgerConfirmedSemanticTypeReader``
        mirroring L4's ``LedgerLineageEdgeReader``.

    Tenant isolation rides on ``company_id`` — every call carries the
    tenant scope and the impl MUST honor it. There is no global
    "all-tenants" read path through this Protocol; downstream auditing
    relies on the scoped read.

    Replay-stability: implementations MUST be order-deterministic for
    a given ``(company_id, table_id, column)`` so re-running the same
    classification discovery yields the same proposed classifications.
    """

    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ConfirmedSemanticTypeRecord]:
        """Return the L5-confirmed semantic types for ``(table_id, column)``.

        Filter contract:

          * State = "confirmed" on
            :class:`wormbase_ledger.SemanticTypeConfirmedPayload`'s
            sister projection ``projection_semantic_types``.
          * Per-(table_id, column) match: types WHERE
            ``table_id = <table_id> AND column = <column>``.

        A single column MAY have multiple confirmed semantic types
        (e.g. ``user_email`` confirmed as ``email`` AND ``pii_name``)
        — L6's classification strategy maps each to a candidate
        classification and lets the composite dedup.

        Returns the empty list when no confirmed types match; callers
        treat this as a no-op (the strategy proposes no
        classifications via the semantic-type path; the
        ``naming_pattern`` + ``domain_default`` strategies still fire
        independently).
        """
        ...


@dataclass(frozen=True)
class ProposedColumnClassification:
    """A candidate column-classification proposal from an L6 strategy.

    Designed to fold one-to-one onto a ``column_classification_proposed``
    ledger entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.ColumnClassificationProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedColumnClassification`.

    Fields:

      * ``classification_id`` — deterministic hash of
        ``(table_id, column, classification_level, strategy)``. Same
        logical proposal → same id. See :func:`make_classification_id`.
        Note ``strategy`` IS in the hash (unlike L5) so each strategy's
        per-column-per-level proposal is its own projection row — admin
        queue can compare strategies side-by-side.
      * ``table_id`` — canonical
        ``"<source_id>.<schema>.<table>"`` identifier.
      * ``column`` — column name on the source side.
      * ``classification_level`` — one of :data:`ClassificationLevel`
        (the 5-value Literal).
      * ``upstream_semantic_type_id`` — cross-axis link back to L5's
        ``projection_semantic_types.type_id`` when the strategy was
        ``semantic_type``; ``None`` for ``naming_pattern`` /
        ``domain_default`` strategies that don't consult L5. The
        /lake/column-classification surface renders a "view L5 semantic
        type →" link when this field is set.
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary.
      * ``strategy`` — open-enum identifier (``"semantic_type"`` |
        ``"naming_pattern"`` | ``"domain_default"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/column-classification`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g. ``{"semantic_type": "pii_ssn",
        "upstream_type_confidence": 0.95}``).
    """

    classification_id: str
    table_id: str
    column: str
    classification_level: ClassificationLevel
    upstream_semantic_type_id: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class ColumnClassificationStrategy(Protocol):
    """Proposes candidate column-classification levels for a column.

    Composable via Optional-Effect Injection (doctrine case 13). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter (see the composite metrics
    surface in :mod:`.composite`).

    All implementations are async + non-mutating; calling
    :meth:`propose` twice on the same inputs returns the same outputs
    modulo set semantics (replay stability).
    """

    name: str  # strategy identifier (``"semantic_type"`` etc.)

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ProposedColumnClassification]:
        """Return the proposed classifications for ``(table_id, column)``.

        ``company_id`` is threaded through so cross-axis-reading
        strategies (e.g. :class:`.strategies.SemanticTypeClassificationStrategy`)
        can scope their lookups by tenant.
        """
        ...


def make_classification_id(
    *,
    table_id: str,
    column: str,
    classification_level: str,
    strategy: str,
) -> str:
    """Deterministic hash for column-classification proposal identity.

    The hash is replay-stable: same logical proposal → same
    ``classification_id`` across runs, Python interpreters, machines.
    This is the dedup key for both the composite (within a single
    strategy) and the projection fold (collapsing re-proposals by the
    same strategy onto one row).

    Uses SHA-256 over a ``"|"``-joined canonical tuple, truncated to 32
    hex chars (128 bits — collision-resistant for the classification-
    proposal cardinality regime). Mirrors the L3 :func:`make_edge_id`,
    L7 :func:`make_check_id`, L4 :func:`make_impact_id`, and L5
    :func:`make_type_id` shape.

    Note: ``strategy`` IS part of the hash (unlike L5's
    :func:`make_type_id` which omits it). Rationale per spec §4.4:
    L6 wants each strategy's per-column-per-level proposal to be its
    own projection row so the admin queue can compare strategies side-
    by-side. ``confidence`` and ``reasoning`` are deliberately NOT in
    the hash — re-running the same strategy with tuned confidences
    should dedup, not multiply.

    All four tuple components are non-empty strings on a valid
    proposal; callers SHOULD enforce non-emptiness before hashing (the
    ledger boundary enforces it at write time).
    """
    parts = [table_id, column, classification_level, strategy]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Producer-side cross-axis Protocol — NEW on the L6 side for the L6→L4 chain.
#
# L6's :class:`ConfirmedSemanticTypeReader` (above) is the *consumer-side*
# Protocol L6 introduced to read L5 — the convention being "the consumer
# owns the Protocol that describes what it reads from a producer". The
# Protocol below inverts that convention slightly: it is owned by L6 (the
# producer of the data) but the read pattern it describes is the one L4
# (consumer) needs. This sits on L6's side because the data domain
# (column classifications, ClassificationLevel) is L6-owned; placing the
# Protocol+Record on L6's side avoids forcing L4 to import the
# ClassificationLevel taxonomy from L6 to project it back through a
# consumer-owned Protocol.
#
# This is the **first producer-side cross-axis Protocol** in the lake-side
# stack (L4's LineageEdgeReader is consumer-side at L4; L6's
# ConfirmedSemanticTypeReader is consumer-side at L6). The L6→L4 chain
# is the **5th cross-axis chain** overall.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmedClassificationRecord:
    """Cross-axis projection of an L6 confirmed column-level classification.

    Exposes the minimum fields L4's governance-impact strategy needs;
    deliberately a subset of L6's full
    :class:`ProposedColumnClassification` + state-fold payload.

    Coupling-minimization principle (mirrors :class:`ConfirmedSemanticTypeRecord`
    and L4's :class:`LineageEdgeRecord`): adding a field to L6's full
    classification payload should NOT force a change here. The producer-
    owned-Protocol pattern trades zero-coupling-cost-on-the-consumer for
    a small adapter surface on the worm-core wiring side.

    Fields:

      * ``classification_id`` — L6's deterministic classification identity
        (see :func:`make_classification_id`). L4's governance strategy
        threads this through onto the proposed impact's
        ``evidence["upstream_classification_id"]`` so the impact row
        links back to the originating L6 confirmation (the cross-axis
        chain that powers the "view L6 classification →" link on
        /lake/schema-impact rows).
      * ``source_id`` — the originating source (extracted from
        ``table_id`` via ``"<source_id>.<schema>.<table>"`` grammar).
        Surfaced so L4's strategy can scope its lookup by the same
        source it's reasoning over.
      * ``table_id`` — canonical ``"<source_id>.<schema>.<table>"``
        identifier; matches L6 payload field directly.
      * ``column`` — column name on the source side; matches L6 payload
        field directly.
      * ``classification_level`` — the L6-confirmed governance level (one
        of :data:`ClassificationLevel`). L4's governance strategy maps
        each level to an impact-elevation profile (``regulated`` →
        critical, ``pii`` / ``confidential`` → high, others → no
        elevation per spec).
      * ``confirmed_at`` — the platform clock time of the confirmation,
        threaded for audit / "stale-elevation" surfacing on the L4 row.
      * ``confirmed_by_person_id`` — WormBase-internal Person UUID of the
        operator who confirmed; threaded for audit.
    """

    classification_id: str
    source_id: str
    table_id: str
    column: str
    classification_level: ClassificationLevel
    confirmed_at: datetime
    confirmed_by_person_id: str


@runtime_checkable
class ConfirmedClassificationReader(Protocol):
    """**Producer-side cross-axis read Protocol — first instance on L6.**

    Exposes L6's confirmed column-level classifications to other axes
    (L4 today, future consumers as needed). The Protocol is intentionally
    scoped to the ``(source_id, src_column, company_id) → [confirmed
    classifications]`` lookup pattern that L4's
    :class:`wormbase_agent_gateway.schema_impact.strategies.GovernanceClassificationImpactStrategy`
    needs; additional methods join the Protocol only when an axis
    genuinely needs them.

    This is the **second L6-owned Reader Protocol** (after
    :class:`ConfirmedSemanticTypeReader` for L5→L6) but the **first
    *producer-side* cross-axis Protocol** in the lake-side stack — the
    convention so far has been consumer-owned. Producer-side ownership
    sits here because:

      * The :data:`ClassificationLevel` taxonomy lives on L6; placing
        the Reader Protocol on L4's side would force L4 to import L6's
        taxonomy.
      * L4 is the first cross-axis consumer; if/when a second consumer
        (e.g. a future audit axis) arrives, the Protocol stays where it
        is and the new consumer imports it.

    Tenant isolation rides on ``company_id`` — every call carries the
    tenant scope and the impl MUST honor it. There is no global
    "all-tenants" read path through this Protocol; downstream auditing
    relies on the scoped read.

    Replay-stability: implementations MUST be order-deterministic for a
    given ``(company_id, source_id, src_column)`` so re-running the same
    governance-impact elevation yields the same proposed impacts.
    """

    async def list_confirmed_classifications_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id: UUID,
    ) -> list[ConfirmedClassificationRecord]:
        """Return the L6-confirmed classifications for ``(source_id, src_column)``.

        Filter contract:

          * State = "confirmed" on L6's
            :class:`wormbase_ledger.ColumnClassificationConfirmedPayload`'s
            sister fold over ``column_classification_proposed/confirmed/
            rejected`` (the L6 projection state machine).
          * Source-column match: classifications WHERE
            ``column = <src_column> AND table_id LIKE "<source_id>.%"``.

        A single column MAY have multiple confirmed classifications
        across strategies (e.g. ``customer_email`` confirmed as ``pii``
        via ``semantic_type`` strategy AND ``internal`` via
        ``domain_default``). L4's governance strategy elevates based on
        the **highest-severity** confirmed level among the set.

        Returns the empty list when no confirmed classifications match;
        callers treat this as a no-op (the strategy proposes no
        governance-elevated impacts).
        """
        ...
