"""L3 lineage-discovery — composite service.

:class:`CompositeLineageInferenceService` composes any subset of the 3
strategies (NamingHeuristic, SampleOverlap, DbtManifest) via Optional-
Effect Injection (doctrine case 9). Each strategy slot is independently
``None``-able; missing slots short-circuit to empty edge lists and
increment the composite's no-op telemetry counter.

The composite is itself a :class:`LineageInferenceService` — the
Compounding factory only ever sees one service interface and doesn't
need to know which strategies are wired in.

Merge contract:

  * Edges are deduplicated by ``edge_id`` (deterministic hash of the
    canonical endpoint tuple — see :func:`make_edge_id`).
  * When multiple strategies propose the same edge, the highest-
    confidence proposal wins on confidence + reasoning.
  * ``evidence`` is a merged dict keyed by strategy name; each
    strategy's evidence payload sits at ``evidence[<strategy>]``.
  * ``reasoning`` is a composite of all contributing strategies'
    explanations joined with ``"; "`` and ordered by encounter.
  * ``strategy`` on the merged edge is ``"composite"`` (so downstream
    can tell merged edges apart from single-strategy edges).

Backed by the shared :class:`LakeLoopComposite` generic (extracted on
2026-05-15 — OptionalEffectGuard precedent fired with L4 close-out).
The public surface, metric keys, and merge behaviour stay byte-
identical to the pre-extraction implementation; the three lake-side
axes (L3, L7, L4) now share one composite implementation while keeping
their per-axis wrappers, ledger payloads, projections, and dashboard
pages duplicated as before.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import InferredEdge, make_edge_id
from .strategies import (
    DbtManifestStrategy,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
)

if TYPE_CHECKING:
    from .protocol import CatalogTable

__all__ = ["CompositeLineageInferenceService"]


def _edge_identity(edge: InferredEdge) -> str:
    """Cluster key for the L3 composite — :attr:`InferredEdge.edge_id`."""
    return edge.edge_id


def _merge_lineage_cluster(proposals: list[InferredEdge]) -> InferredEdge:
    """Merge proposals sharing one edge_id (defensive: re-hash to sanity-check).

    Wraps :func:`wormbase_agent_gateway.lake_loop.default_cluster_merge`
    with the L3-specific defensive re-hash: the canonical identity must
    match between the cluster key and the freshly-computed
    :func:`make_edge_id`. If a future refactor of the hash diverges
    from the dataclass's :attr:`edge_id` property, this assertion fires
    instead of corrupting the dedup contract silently.
    """
    from wormbase_agent_gateway.lake_loop import default_cluster_merge

    merged = default_cluster_merge(proposals)
    if len(proposals) > 1:
        canonical = make_edge_id(
            src_table_id=merged.src_table_id,
            src_column=merged.src_column,
            tgt_table_id=merged.tgt_table_id,
            tgt_column=merged.tgt_column,
        )
        assert canonical == proposals[0].edge_id, (
            f"edge_id mismatch: cluster key {proposals[0].edge_id!r} vs "
            f"recomputed {canonical!r} — proposals do not share endpoint tuple"
        )
    return merged


class CompositeLineageInferenceService:
    """Composes the 3 lineage strategies via Optional-Effect Injection.

    Each strategy slot accepts ``None``; the composite still implements
    :class:`LineageInferenceService` and returns an empty edge list when
    every strategy is ``None`` (pure no-op — the Compounding factory
    surfaces this as zero proposed edges, identical to "service not
    wired").

    Doctrine: Optional-Effect Injection (case 9). The factory composes
    by passing ``None`` for any strategy that's not enabled in the
    current deployment; per-strategy telemetry counters in
    :meth:`metrics` make the chosen path auditable per Rule 9.

    Strategy execution order: ``naming → dbt_manifest → sample_overlap``
    (cheap-to-expensive — though all three always run when configured;
    the order only fixes encounter order in the composite reasoning
    string for replay stability).

    Implementation: composes a :class:`LakeLoopComposite` (the shared
    generic) with L3-specific case-name (``"lineage_inference"``),
    propose-method (``"infer_edges"``), identity-key (``edge_id``), and
    a defensive merge-cluster hook that re-hashes the canonical edge id
    to catch hash-contract drift.
    """

    name: str = "composite"

    def __init__(
        self,
        *,
        naming: NamingHeuristicStrategy | None = None,
        sample_overlap: SampleOverlapStrategy | None = None,
        dbt_manifest: DbtManifestStrategy | None = None,
    ) -> None:
        self.naming = naming
        self.sample_overlap = sample_overlap
        self.dbt_manifest = dbt_manifest

        # Strategy ordering pinned by tests: naming first → dbt_manifest
        # → sample_overlap. The reasoning string in
        # test_composite_merge_dedup_highest_confidence_wins depends on
        # this order ("naming match" appears before "sample overlap").
        self._composite: LakeLoopComposite[InferredEdge] = LakeLoopComposite[
            InferredEdge
        ](
            case_name="lineage_inference",
            strategies={
                "naming_heuristic": naming,
                "dbt_manifest": dbt_manifest,
                "sample_overlap": sample_overlap,
            },
            propose_method="infer_edges",
            identity_key=_edge_identity,
            proposals_counter_name="edges_proposed",
            merge_cluster=_merge_lineage_cluster,
        )

    async def infer_edges(
        self,
        *,
        source_table: "CatalogTable",
        candidate_targets: "list[CatalogTable]",
        sample_size: int = 1000,
    ) -> list[InferredEdge]:
        """Run all configured strategies; merge + deduplicate by edge_id."""
        return await self._composite.propose(
            source_table=source_table,
            candidate_targets=candidate_targets,
            sample_size=sample_size,
        )

    def metrics(self) -> dict[str, int]:
        """Per-strategy telemetry counters per Optional-Effect doctrine Rule 9.

        Keys (byte-identical to the pre-extraction shape):

          * ``lineage_inference_invocations`` — total composite calls.
          * ``lineage_inference_strategy_invocations.<name>`` — per-
            strategy fire count. Zero for ``None`` strategies.
          * ``lineage_inference_edges_proposed`` — total merged edges
            returned across all invocations.
          * ``lineage_inference_no_op`` — invocations where all
            strategies were ``None`` (Optional-Effect absent path).
        """
        return self._composite.metrics()
