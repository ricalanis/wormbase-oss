"""L3 lineage-discovery — Protocol + dataclasses + edge-id hash.

Surfaces:

  * :class:`InferredEdge` — a candidate lineage edge from one inference
    strategy. Carries the deterministic ``edge_id`` (via
    :func:`make_edge_id`), the directional endpoints, a 0.0–1.0
    ``confidence``, a ``strategy`` identifier, a human-readable
    ``reasoning`` string and a structured ``evidence`` dict.
  * :class:`CatalogTable` — a strategy-input reference to a table in the
    catalog. Strategies see ``(source_table, candidate_targets[])`` and
    walk the columns; the wrapping ``infer_edges`` call is the only
    contact point with the catalog.
  * :class:`LineageInferenceConfig` — a frozen tunables bundle the
    composite + factory thread through to per-strategy constructors.
  * :class:`LineageInferenceService` — the runtime :class:`typing.Protocol`
    every strategy + the composite implements. Optional-Effect Injection
    compatible (the composite accepts ``None`` for any strategy slot).
  * :func:`make_edge_id` — deterministic SHA-256 hash of the canonical
    edge tuple. Replay-stable across runs; same logical edge → same id.

The Sub-wave A ledger contract pairs an edge_id to one
``lineage_edge_proposed`` row; the projection_lineage_edges fold
deduplicates on it. The hash MUST be stable across Python interpreters
so projection writes from one run can be confirmed by another.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CatalogTable",
    "InferredEdge",
    "LineageInferenceConfig",
    "LineageInferenceService",
    "make_edge_id",
]


@dataclass(frozen=True)
class InferredEdge:
    """A candidate lineage edge from an inference strategy.

    Designed to fold one-to-one onto a ``lineage_edge_proposed`` ledger
    entry: every field has a direct payload counterpart (see
    ``LineageEdgeProposedPayload`` in ``wormbase_ledger.entries``).

    The composite returns a deduplicated list of these; the Compounding
    factory's promotion_action writes one ledger entry per InferredEdge.

    Fields:

      * ``src_table_id`` / ``tgt_table_id`` — canonical
        ``"<source_id>.<schema>.<table>"`` identifiers. Same shape as
        Wave-1's wormbase-catalog-mirror table-id grammar.
      * ``src_column`` / ``tgt_column`` — column names; ``None`` means
        the edge is whole-table (no column-level pin), which is common
        for dbt-manifest-derived lineage where the manifest exposes
        model refs but not column-grain.
      * ``confidence`` — strategy-emitted score in [0.0, 1.0]. Validated
        at the ledger boundary (see
        ``LineageEdgeProposedPayload._confidence_in_unit_range``).
      * ``strategy`` — open-enum identifier (``"naming_heuristic"`` |
        ``"sample_overlap"`` | ``"dbt_manifest"`` | future plug-ins).
      * ``reasoning`` — human-readable explanation surfaced on the
        admin /trace edge-detail view.
      * ``evidence`` — strategy-specific structured payload preserved
        verbatim through the fold (e.g.
        ``{"sample_overlap_ratio": 0.87, "sampled_n": 1000}``).
    """

    src_table_id: str
    src_column: str | None
    tgt_table_id: str
    tgt_column: str | None
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]

    @property
    def edge_id(self) -> str:
        """Deterministic edge identity; see :func:`make_edge_id`."""
        return make_edge_id(
            src_table_id=self.src_table_id,
            src_column=self.src_column,
            tgt_table_id=self.tgt_table_id,
            tgt_column=self.tgt_column,
        )


@dataclass(frozen=True)
class CatalogTable:
    """Reference to a catalog table — strategy input.

    Strategies receive a single ``source_table`` plus a list of
    ``candidate_targets`` and emit any inferred edges between them.

    ``columns`` is the ordered tuple of column names (frozen for
    hashability + replay stability). ``source_kind`` identifies the
    upstream connector kind (``"dbt"`` | ``"snowflake"`` | ``"postgres"``
    | ...) so strategies that only fire for specific kinds (e.g.
    DbtManifestStrategy) can early-out cheaply. ``metadata`` carries the
    raw catalog blob the strategy may need (e.g. dbt manifest entry,
    row-count estimate, sample-tolerance flags).
    """

    table_id: str
    columns: tuple[str, ...]
    source_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LineageInferenceConfig:
    """Frozen tunables bundle for the composite + strategies.

    Threaded through the Compounding factory to keep the strategy
    constructor surface narrow. Defaults preserve the Sub-wave B
    behaviour pinned in tests; production overrides via env knobs in
    the boot wire (lands Sub-wave C).
    """

    # Naming heuristic
    edit_distance_max: int = 2
    min_shared_prefix: int = 3
    # Sample overlap
    jaccard_threshold: float = 0.5
    value_richness_min: int = 10
    max_table_size: int = 10_000_000
    sample_size: int = 1000


@runtime_checkable
class LineageInferenceService(Protocol):
    """Infers candidate lineage edges between catalog tables.

    Composable via Optional-Effect Injection (doctrine case 9). Each
    concrete strategy can be independently ``None`` on the composite;
    missing strategies fall back to empty edge lists and increment the
    composite's no-op telemetry counter (see
    :class:`CompositeLineageInferenceService.metrics`).

    All implementations are async + non-mutating; calling ``infer_edges``
    twice on the same inputs returns the same outputs modulo set
    semantics (replay stability).
    """

    name: str  # strategy identifier (``"naming_heuristic"`` etc.)

    async def infer_edges(
        self,
        *,
        source_table: CatalogTable,
        candidate_targets: list[CatalogTable],
        sample_size: int = 1000,
    ) -> list[InferredEdge]:
        """Return the inferred edges from ``source_table`` to candidates.

        ``sample_size`` is a hint for sampling-based strategies; pure-
        metadata strategies (NamingHeuristic, DbtManifest) ignore it.
        """
        ...


def make_edge_id(
    *,
    src_table_id: str,
    src_column: str | None,
    tgt_table_id: str,
    tgt_column: str | None,
) -> str:
    """Deterministic hash for the edge identity.

    The hash is replay-stable: same logical edge → same edge_id across
    runs, Python interpreters, machines. This is the dedup key for both
    the composite (merging multi-strategy proposals) and the projection
    fold (collapsing re-proposals onto one row).

    Uses SHA-256 over a ``"|"``-joined canonical tuple, truncated to 32
    hex chars (128 bits — collision-resistant for the lineage-edge
    cardinality regime: even 10^9 edges has < 10^-18 collision risk).

    ``None`` columns are serialised as empty strings so a whole-table
    edge stays distinct from a column-grain edge to the same table.
    """
    parts = [
        src_table_id,
        src_column or "",
        tgt_table_id,
        tgt_column or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
