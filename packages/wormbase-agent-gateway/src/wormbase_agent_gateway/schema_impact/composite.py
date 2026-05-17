"""L4 schema-evolution-impact — composite service.

:class:`CompositeSchemaImpactService` composes any subset of the 3
strategies (LineageEdge, DbtTest, TypeCoercion) via Optional-Effect
Injection (doctrine case 11). Each strategy slot is independently
``None``-able; missing slots short-circuit to empty proposal lists and
increment the composite's no-op telemetry counter.

The composite is itself a :class:`SchemaImpactService` — the
Compounding factory only ever sees one service interface and doesn't
need to know which strategies are wired in.

Merge contract (mirrors L3 :class:`CompositeLineageInferenceService`
and L7 :class:`CompositeQualityProposalService`):

  * Proposals are deduplicated by ``impact_id`` (deterministic hash of
    the canonical tuple — see :func:`.protocol.make_impact_id`).
  * When multiple strategies propose the same impact, the highest-
    confidence proposal wins on confidence + reasoning.
  * ``evidence`` is a merged dict keyed by strategy name; each
    strategy's evidence payload sits at ``evidence[<strategy>]``.
  * ``reasoning`` is a composite of all contributing strategies'
    explanations joined with ``"; "`` and ordered by encounter.
  * ``strategy`` on the merged proposal is ``"composite"`` (so
    downstream can tell merged proposals apart from single-strategy
    proposals).
  * ``upstream_lineage_edge_id`` is taken from the highest-confidence
    proposal that has one (typically the lineage_edge or type_coercion
    strategy's edge); ``None`` when no contributing strategy reports
    one.
  * ``impact_kind`` taken from the highest-confidence proposal (in
    case strategies disagree on classification for the same canonical
    tuple — defensive).

The case-11 framing in the doctrine extends cases 9 (L3) + 10 (L7) to
a third L-axis Compounding service with the same Optional-Effect
Injection contract, plus the new cross-axis read dimension carried in
the strategies (see :class:`.protocol.LineageEdgeReader`). All three
cases share the per-strategy telemetry counters required by Rule 9.

Backed by the shared :class:`LakeLoopComposite` generic (extracted on
2026-05-15 — OptionalEffectGuard precedent fired with this axis's
close-out). The public surface, metric keys, and merge behaviour stay
byte-identical to the pre-extraction implementation. L4 is the only
axis with a non-default merge winner — it threads
``upstream_lineage_edge_id`` through a fallback (winner.upstream OR
first non-None across the cluster) — so it supplies a custom
``merge_cluster`` hook around the shared default.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from wormbase_agent_gateway.lake_loop import (
    LakeLoopComposite,
    default_cluster_merge,
)

from .protocol import (
    ColumnChange,
    ProposedImpact,
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

__all__ = ["CompositeSchemaImpactService"]


def _impact_identity(impact: ProposedImpact) -> str:
    """Cluster key for L4 composite — :attr:`ProposedImpact.impact_id`."""
    return impact.impact_id


def _merge_schema_impact_cluster(
    proposals: list[ProposedImpact],
) -> ProposedImpact:
    """Merge proposals sharing one impact_id with L4-specific extras.

    Delegates structural fields (strategy / reasoning / evidence) to
    :func:`wormbase_agent_gateway.lake_loop.default_cluster_merge`, then
    overlays the two L4-specific extras:

      * ``upstream_lineage_edge_id`` — prefer the winner's edge id;
        fall back to the first proposal with a non-None edge id (some
        strategies emit on bare type metadata without an L3 edge).
      * Defensive re-hash of ``impact_id`` to catch hash-contract drift.

    The default merge already preserves ``impact_kind`` via
    :func:`dataclasses.replace` of the highest-confidence winner, so no
    extra threading is required there.
    """
    merged = default_cluster_merge(proposals)
    if len(proposals) == 1:
        return merged

    # Defensive: re-hash to surface a future refactor of make_impact_id.
    head = proposals[0]
    canonical_id = make_impact_id(
        source_id=head.source_id,
        src_table=head.src_table,
        src_column=head.src_column,
        change_kind=head.change_kind,
        tgt_table_id=head.tgt_table_id,
        tgt_column=head.tgt_column,
    )
    assert canonical_id == head.impact_id, (
        f"impact_id mismatch: cluster key {head.impact_id!r} vs recomputed "
        f"{canonical_id!r} — proposals do not share canonical tuple"
    )

    # Thread upstream_lineage_edge_id through the merge: prefer the
    # winner's edge id; fall back to any proposal that has one.
    # ``merged`` already carries the winner's edge id via the default
    # dataclass replace; only override on None-fallback.
    if merged.upstream_lineage_edge_id is None:
        for p in proposals:
            if p.upstream_lineage_edge_id is not None:
                merged = replace(merged, upstream_lineage_edge_id=p.upstream_lineage_edge_id)
                break

    return merged


class CompositeSchemaImpactService:
    """Composes the 3 schema-impact strategies via Optional-Effect Injection.

    Each strategy slot accepts ``None``; the composite still implements
    :class:`.protocol.SchemaImpactService` and returns an empty proposal
    list when every strategy is ``None`` (pure no-op — the Compounding
    factory surfaces this as zero proposed impacts, identical to
    "service not wired").

    Doctrine: Optional-Effect Injection (case 11 — L4 schema-evolution-
    impact, parallel to case 9's L3 lineage discovery + case 10's L7
    quality discovery; first case to carry a cross-axis read via the
    :class:`.protocol.LineageEdgeReader` Protocol injected into
    strategies). The factory composes by passing ``None`` for any
    strategy that's not enabled in the current deployment; per-strategy
    telemetry counters in :meth:`metrics` make the chosen path
    auditable per Rule 9.

    Strategy execution order: ``lineage_edge → dbt_test → type_coercion``
    (cross-axis cost-ordered; the order only fixes encounter order in
    the composite reasoning string for replay stability).

    Implementation: composes a :class:`LakeLoopComposite` (the shared
    generic) with L4-specific case-name (``"schema_impact"``),
    propose-method (``"propose_impacts"``), identity-key (``impact_id``),
    and a custom merge-cluster hook that threads ``upstream_lineage_edge_id``
    through the merge with a None-fallback to the first contributor
    that carried one.
    """

    name: str = "composite"

    def __init__(
        self,
        *,
        lineage_edge: LineageEdgeImpactStrategy | None = None,
        dbt_test: DbtTestImpactStrategy | None = None,
        type_coercion: TypeCoercionImpactStrategy | None = None,
        governance_classification: (
            GovernanceClassificationImpactStrategy | None
        ) = None,
        semantic_type: SemanticTypeImpactStrategy | None = None,
        acknowledged_drift: (
            AcknowledgedDriftImpactStrategy | None
        ) = None,
    ) -> None:
        self.lineage_edge = lineage_edge
        self.dbt_test = dbt_test
        self.type_coercion = type_coercion
        self.governance_classification = governance_classification
        self.semantic_type = semantic_type
        self.acknowledged_drift = acknowledged_drift

        # Strategy ordering pinned by tests:
        # lineage_edge → dbt_test → type_coercion → governance_classification
        # → semantic_type → acknowledged_drift.
        # The reasoning string in
        # test_composite_merge_dedup_when_two_strategies_propose_same_impact
        # asserts "L3 lineage edge" appears before "CAST int AS varchar",
        # which is what the lineage_edge-first ordering produces.
        # Governance + semantic_type + acknowledged_drift are the cross-
        # axis-elevation strategies — their proposals SHARE
        # ``target=src`` so the composite-merge dedup activates when
        # multiple cross-axis strategies hit the same canonical tuple
        # (per L5→L4 close-out recipe addendum #2: same canonical
        # tuple → one row with multiple evidence keys + chips + links).
        # Ordering is stable so the merged reasoning string is replay-
        # deterministic. Acknowledged_drift is appended last as the
        # 7th cross-axis chain (L4↦L2) — the first BIDIRECTIONAL chain.
        self._composite: LakeLoopComposite[ProposedImpact] = LakeLoopComposite[
            ProposedImpact
        ](
            case_name="schema_impact",
            strategies={
                "lineage_edge": lineage_edge,
                "dbt_test": dbt_test,
                "type_coercion": type_coercion,
                "governance_classification": governance_classification,
                "semantic_type": semantic_type,
                "acknowledged_drift": acknowledged_drift,
            },
            propose_method="propose_impacts",
            identity_key=_impact_identity,
            proposals_counter_name="impacts_proposed",
            merge_cluster=_merge_schema_impact_cluster,
        )

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: UUID,
    ) -> list[ProposedImpact]:
        """Run all configured strategies; merge + dedup by impact_id."""
        return await self._composite.propose(
            source_id=source_id,
            src_table=src_table,
            change=change,
            company_id=company_id,
        )

    def metrics(self) -> dict[str, int]:
        """Per-strategy telemetry counters per Optional-Effect doctrine Rule 9.

        Keys (byte-identical to the pre-extraction shape):

          * ``schema_impact_invocations`` — total composite calls.
          * ``schema_impact_strategy_invocations.<name>`` — per-strategy
            fire count. Zero for ``None`` strategies.
          * ``schema_impact_impacts_proposed`` — total merged proposals
            returned across all invocations.
          * ``schema_impact_no_op`` — invocations where all strategies
            were ``None`` (Optional-Effect absent path).
        """
        return self._composite.metrics()


# Re-export Any+UUID dependents so the module's public surface stays
# stable for callers that import from this file directly (currently
# only the schema_impact subpackage __init__ — but kept symmetric with
# the pre-extraction file for ease of inspection).
_ = (Any, UUID)
