"""L7 quality-check discovery — Protocol + dataclasses + check-id hash.

Surfaces:

  * :data:`QualityCheckKind` — strict 7-value :class:`typing.Literal`
    covering the L7 check taxonomy (mirrors
    :class:`wormbase_ledger.entries.QualityCheckProposedPayload.check_kind`).
  * :class:`ProposedQualityCheck` — strategy output dataclass; folds
    1:1 onto a ``quality_check_proposed`` ledger entry.
  * :class:`QualityCheckProposalService` — the runtime
    :class:`typing.Protocol` every strategy + the composite implements.
    Optional-Effect Injection compatible (the composite accepts ``None``
    for any strategy slot).
  * :func:`make_check_id` — deterministic SHA-256 hash of the canonical
    check tuple. Replay-stable across runs; same logical check → same
    ``check_id``.

Structurally mirrors :mod:`wormbase_agent_gateway.lineage.protocol` so
the two L-axis Compounding services share the same Optional-Effect
Injection shape (doctrine cases 9 + 10).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

# CatalogTable is shared with the lineage axis — the strategy input
# shape is identical (same source_kind / columns / metadata grammar),
# so the lineage module's dataclass is the canonical source. Importing
# here keeps the public surface symmetric without duplicating the
# definition (see §3.3 of the L7 design spec — "Reuse CatalogTable
# from lineage/protocol.py").
from wormbase_agent_gateway.lineage.protocol import CatalogTable

__all__ = [
    "CatalogTable",
    "ProposedQualityCheck",
    "QualityCheckKind",
    "QualityCheckProposalService",
    "make_check_id",
]


QualityCheckKind = Literal[
    "not_null",
    "unique",
    "freshness",
    "row_count_range",
    "enum_membership",
    "type_stability",
    "value_range",
]
"""The 7 quality-check kinds the L7 axis can propose.

Mirrors the strict :class:`typing.Literal` on
:class:`wormbase_ledger.entries.QualityCheckProposedPayload.check_kind`
(Sub-wave A). A new kind requires an additive ledger migration AND a
matching change here — the two must stay in lockstep.

Per-kind ``config`` shape (carried on
:attr:`ProposedQualityCheck.config`):

  * ``not_null`` — ``{}``  (column-level, no parameters)
  * ``unique`` — ``{}``  (column-level, no parameters)
  * ``freshness`` — ``{"max_age_hours": <int>}``  (column-level, on a
    timestamp column)
  * ``row_count_range`` — ``{"min_rows": <int>, "max_rows": <int>}``
    (table-level; ``column`` is ``None``)
  * ``enum_membership`` — ``{"allowed_values": [<str>, ...]}``
    (column-level)
  * ``type_stability`` — ``{"expected_type": <str>}``  (column-level)
  * ``value_range`` — ``{"min": <number>, "max": <number>}``
    (column-level, numeric)
"""


@dataclass(frozen=True)
class ProposedQualityCheck:
    """A candidate quality check from an inference strategy.

    Designed to fold one-to-one onto a ``quality_check_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.QualityCheckProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedQualityCheck`.

    Fields:

      * ``check_id`` — deterministic hash of
        ``(table_id, check_kind, column, normalized_config)``; same
        logical check → same id. See :func:`make_check_id`.
      * ``table_id`` — canonical
        ``"<source_id>.<schema>.<table>"`` identifier (same shape as
        Wave-1's wormbase-catalog-mirror table-id grammar).
      * ``column`` — column name; ``None`` means a table-level check
        (e.g. ``row_count_range`` or a table-grain ``freshness``).
      * ``check_kind`` — one of :data:`QualityCheckKind`.
      * ``config`` — kind-specific parameter dict (see
        :data:`QualityCheckKind` docstring for the per-kind shape).
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary (see
        :class:`wormbase_ledger.entries.QualityCheckProposedPayload`).
      * ``strategy`` — open-enum identifier (``"schema_pattern"`` |
        ``"dbt_tests"`` | ``"historical_stats"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/quality`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g.
        ``{"observed_null_ratio": 0.02, "sampled_n": 1000}``).
      * ``upstream_semantic_type_id`` — **cross-axis link** back to
        L5's ``projection_semantic_types.type_id`` when the proposal
        came from the ``semantic_type`` strategy (the L5→L7 cross-axis
        chain — 4th cross-axis chain after L4→L3, L6→L5, L8→L5).
        ``None`` for the existing ``schema_pattern`` / ``dbt_tests`` /
        ``historical_stats`` strategies which don't consult L5. The
        /lake/quality surface renders a "view L5 semantic type →" link
        when this field is set. Additive field with default ``None``
        for back-compat — pre-existing strategies + ledger entries
        round-trip unchanged.
    """

    check_id: str
    table_id: str
    column: str | None
    check_kind: QualityCheckKind
    config: dict[str, Any]
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]
    upstream_semantic_type_id: str | None = None


@runtime_checkable
class QualityCheckProposalService(Protocol):
    """Proposes candidate quality checks for a catalog table.

    Composable via Optional-Effect Injection (doctrine case 10). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter (see
    :class:`CompositeQualityProposalService.metrics`).

    All implementations are async + non-mutating; calling
    :meth:`propose_checks` twice on the same inputs returns the same
    outputs modulo set semantics (replay stability).
    """

    name: str  # strategy identifier (``"schema_pattern"`` etc.)

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """Return the proposed quality checks for ``table``.

        ``sample_size`` is a hint for sampling-based strategies; pure-
        metadata strategies (``SchemaPatternStrategy``,
        ``DbtTestsStrategy``) ignore it.

        ``company_id`` is the tenant scope; threaded through so
        cross-axis-reading strategies (e.g.
        :class:`.strategies.SemanticTypeQualityCheckStrategy` — the
        L5→L7 cross-axis chain, 4th in the lake-side stack) can call
        their upstream Reader with the right tenant. Existing
        ``schema_pattern`` / ``dbt_tests`` / ``historical_stats``
        strategies ignore the value (their reads are model-scoped or
        table-scoped, not tenant-scoped). Default ``None`` for
        byte-identical back-compat — callers that do not yet pass
        company_id (worm-core's L7 reactivity prior to the L5→L7 wire)
        keep working unchanged.
        """
        ...


def make_check_id(
    *,
    table_id: str,
    check_kind: str,
    column: str | None,
    normalized_config: dict[str, Any],
) -> str:
    """Deterministic hash for the check identity.

    The hash is replay-stable: same logical check → same ``check_id``
    across runs, Python interpreters, machines. This is the dedup key
    for both the composite (merging multi-strategy proposals) and the
    projection fold (collapsing re-proposals onto one row).

    Uses SHA-256 over a ``"|"``-joined canonical tuple, truncated to 32
    hex chars (128 bits — collision-resistant for the quality-check
    cardinality regime). Mirrors the L3 :func:`make_edge_id` shape.

    ``column`` ``None`` is serialised as the empty string so a
    table-level check stays distinct from a column-grain check on the
    same table.

    ``normalized_config`` is JSON-serialised with ``sort_keys=True`` so
    semantically-equivalent configs with different key orders produce
    the same hash. Callers SHOULD pass already-normalized dicts (e.g.
    ``{"max_age_hours": 24}``, not ``{"max_age_hours": 24.0}``); the
    hash is sensitive to value types.
    """
    parts = [
        table_id,
        check_kind,
        column or "",
        json.dumps(normalized_config, sort_keys=True),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
