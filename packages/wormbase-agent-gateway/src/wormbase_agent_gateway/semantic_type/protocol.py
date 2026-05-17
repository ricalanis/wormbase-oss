"""L5 semantic-type fingerprinting — Protocol + dataclasses + type-id hash.

Surfaces:

  * :data:`SemanticType` — strict 19-value :class:`typing.Literal` covering
    the canonical semantic-type taxonomy. Mirrors
    :attr:`wormbase_ledger.entries.SemanticTypeProposedPayload.semantic_type`
    exactly — adding a value here requires a matching additive ledger
    migration. New types require explicit doctrine review.
  * :class:`ProposedSemanticType` — strategy output dataclass; folds 1:1
    onto a ``semantic_type_proposed`` ledger entry.
  * :class:`FingerprintStrategy` — the runtime :class:`typing.Protocol`
    every strategy + the composite implements. Optional-Effect Injection
    compatible (the composite accepts ``None`` for any strategy slot).
  * :func:`make_type_id` — deterministic SHA-256 hash of the canonical
    ``(table_id, column, semantic_type)`` tuple. Replay-stable across
    runs; same logical proposal → same ``type_id``.

Structurally mirrors :mod:`wormbase_agent_gateway.lineage.protocol`,
:mod:`wormbase_agent_gateway.quality.protocol`, and
:mod:`wormbase_agent_gateway.schema_impact.protocol`. Unlike L4, L5 does
NOT introduce a new cross-axis read Protocol — strategies inject the
existing :class:`wormbase_agent_gateway.lineage.SamplerProtocol` (value
sampling) and :class:`wormbase_agent_gateway.quality.HistoricalStatsReader`
(column-level stats) where needed. Reuse > duplication.

Doctrine: Optional-Effect Injection case 12 — first lake-side axis
built on top of :class:`wormbase_agent_gateway.lake_loop.LakeLoopComposite`
from day one (vs L3/L7/L4 which retrofitted the abstraction). Validates
that the shared composite generic shipped at ``a4a62c2`` pays off for new
consumers as designed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = [
    "FingerprintStrategy",
    "ProposedSemanticType",
    "SemanticType",
    "make_type_id",
]


SemanticType = Literal[
    # Identity
    "email",
    "phone_e164",
    "phone_us",
    # Temporal
    "iso_date",
    "iso_datetime",
    "unix_timestamp",
    # Identifiers
    "uuid_v4",
    "uuid_v7",
    "business_id",
    # Geo/locale
    "country_iso",
    "language_iso",
    "currency_iso",
    # PII (sensitive)
    "pii_name",
    "pii_address",
    "pii_ssn",
    "pii_credit_card",
    # Metric
    "metric_count",
    "metric_amount",
    "metric_rate",
    # Catch-all
    "other",
]
"""The 19 canonical semantic-type values L5 can propose.

Mirrors :attr:`wormbase_ledger.entries.SemanticTypeProposedPayload.semantic_type`
exactly. Adding a value requires:

  1. An additive ledger migration extending the payload's Literal.
  2. A matching addition here.
  3. Doctrine review — semantic drift in the enum is hard to reverse
     once strategies start emitting against new values.

Grouping (informational):

  * **Identity** — ``email``, ``phone_e164``, ``phone_us``
  * **Temporal** — ``iso_date``, ``iso_datetime``, ``unix_timestamp``
  * **Identifiers** — ``uuid_v4``, ``uuid_v7``, ``business_id``
  * **Geo/locale** — ``country_iso``, ``language_iso``, ``currency_iso``
  * **PII (sensitive)** — ``pii_name``, ``pii_address``, ``pii_ssn``,
    ``pii_credit_card``
  * **Metric** — ``metric_count``, ``metric_amount``, ``metric_rate``
  * **Catch-all** — ``other``
"""


@dataclass(frozen=True)
class ProposedSemanticType:
    """A candidate semantic-type proposal from an L5 strategy.

    Designed to fold one-to-one onto a ``semantic_type_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    :class:`wormbase_ledger.entries.SemanticTypeProposedPayload`).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per
    :class:`ProposedSemanticType`.

    Fields:

      * ``type_id`` — deterministic hash of
        ``(table_id, column, semantic_type)``. Same logical proposal →
        same id. See :func:`make_type_id`.
      * ``table_id`` — canonical
        ``"<source_id>.<schema>.<table>"`` identifier (same shape as
        Wave-1's wormbase-catalog-mirror table-id grammar).
      * ``column`` — column name on the source side.
      * ``semantic_type`` — one of :data:`SemanticType`.
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary (see
        :class:`wormbase_ledger.entries.SemanticTypeProposedPayload`).
      * ``strategy`` — open-enum identifier (``"column_name"`` |
        ``"value_pattern"`` | ``"distribution"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin ``/lake/semantic-types`` detail panel.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g. ``{"match_count": 18, "sample_n":
        20, "regex": "..."}``).
    """

    type_id: str
    table_id: str
    column: str
    semantic_type: SemanticType
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class FingerprintStrategy(Protocol):
    """Proposes candidate semantic-type fingerprints for a column.

    Composable via Optional-Effect Injection (doctrine case 12). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty proposal lists and increment
    the composite's no-op telemetry counter (see the composite metrics
    surface in :mod:`.composite`).

    All implementations are async + non-mutating; calling
    :meth:`propose` twice on the same inputs returns the same outputs
    modulo set semantics (replay stability).
    """

    name: str  # strategy identifier (``"column_name"`` etc.)

    async def propose(
        self,
        *,
        table_id: str,
        column: str,
        sample_size: int = 20,
    ) -> list[ProposedSemanticType]:
        """Return the proposed semantic-type fingerprints for ``(table_id, column)``.

        ``sample_size`` defaults to 20 — the canonical window for
        value-pattern matching (M/N gate; see
        :class:`.strategies.ValuePatternFingerprintStrategy`). Strategies
        that do not sample (e.g. column-name regex) ignore the parameter.
        """
        ...


def make_type_id(
    *,
    table_id: str,
    column: str,
    semantic_type: str,
) -> str:
    """Deterministic hash for semantic-type proposal identity.

    The hash is replay-stable: same logical proposal → same ``type_id``
    across runs, Python interpreters, machines. This is the dedup key
    for both the composite (merging multi-strategy proposals) and the
    projection fold (collapsing re-proposals onto one row).

    Uses SHA-256 over a ``"|"``-joined canonical tuple, truncated to 32
    hex chars (128 bits — collision-resistant for the type-proposal
    cardinality regime). Mirrors the L3 :func:`make_edge_id`, L7
    :func:`make_check_id`, and L4 :func:`make_impact_id` shape.

    All three tuple components are non-empty strings on a valid
    proposal; callers SHOULD enforce non-emptiness before hashing (the
    ledger boundary enforces it at write time).

    Note: ``confidence`` and ``strategy`` are deliberately NOT part of
    the hash — two strategies proposing the same ``(table_id, column,
    semantic_type)`` MUST collide so the composite can merge them.
    """
    parts = [table_id, column, semantic_type]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
