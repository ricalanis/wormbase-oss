"""L7 quality-check discovery — composite service.

:class:`CompositeQualityProposalService` composes any subset of the 3
strategies (SchemaPattern, DbtTests, HistoricalStats) via Optional-
Effect Injection (doctrine case 10). Each strategy slot is
independently ``None``-able; missing slots short-circuit to empty
proposal lists and increment the composite's no-op telemetry counter.

The composite is itself a :class:`QualityCheckProposalService` — the
Compounding factory only ever sees one service interface and doesn't
need to know which strategies are wired in.

Merge contract (mirrors L3 :class:`CompositeLineageInferenceService`):

  * Proposals are deduplicated by ``check_id`` (deterministic hash of
    the canonical tuple — see :func:`make_check_id`).
  * When multiple strategies propose the same check, the highest-
    confidence proposal wins on confidence + reasoning.
  * ``evidence`` is a merged dict keyed by strategy name; each
    strategy's evidence payload sits at ``evidence[<strategy>]``.
  * ``reasoning`` is a composite of all contributing strategies'
    explanations joined with ``"; "`` and ordered by encounter.
  * ``strategy`` on the merged proposal is ``"composite"`` (so
    downstream can tell merged proposals apart from single-strategy
    proposals).
  * ``config`` — taken from the highest-confidence proposal (the default
    merge winner). When confidence ties, takes the first-encountered.

The case-10 framing in the doctrine extends case-9's lineage shape to
a second L-axis Compounding service with the same Optional-Effect
Injection contract. Both cases share the per-strategy telemetry
counters required by Rule 9.

Backed by the shared :class:`LakeLoopComposite` generic (extracted on
2026-05-15 — OptionalEffectGuard precedent fired with L4 close-out).
The public surface, metric keys, and merge behaviour stay byte-
identical to the pre-extraction implementation.
"""
from __future__ import annotations

from uuid import UUID

from wormbase_agent_gateway.lake_loop import (
    LakeLoopComposite,
    default_cluster_merge,
)

from .protocol import (
    CatalogTable,
    ProposedQualityCheck,
    make_check_id,
)
from .strategies import (
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    SchemaPatternStrategy,
    SemanticTypeQualityCheckStrategy,
)

__all__ = ["CompositeQualityProposalService"]


def _check_identity(check: ProposedQualityCheck) -> str:
    """Cluster key for L7 composite — :attr:`ProposedQualityCheck.check_id`."""
    return check.check_id


def _merge_quality_cluster(
    proposals: list[ProposedQualityCheck],
) -> ProposedQualityCheck:
    """Merge proposals sharing one check_id (defensive: re-hash head).

    Delegates structural fields (strategy / reasoning / evidence) to
    :func:`wormbase_agent_gateway.lake_loop.default_cluster_merge`, then
    asserts the head proposal's canonical id matches the cluster key.
    The assertion catches the case where two distinct configs hash to
    the same cluster key (the merge would silently corrupt the dedup
    contract); it should not fire in practice.
    """
    merged = default_cluster_merge(proposals)
    if len(proposals) > 1:
        head = proposals[0]
        head_canonical = make_check_id(
            table_id=head.table_id,
            check_kind=head.check_kind,
            column=head.column,
            normalized_config=head.config,
        )
        assert head_canonical == head.check_id, (
            f"check_id mismatch: cluster key {head.check_id!r} vs "
            f"recomputed {head_canonical!r} — proposals do not share "
            f"canonical tuple"
        )
    return merged


class CompositeQualityProposalService:
    """Composes the 3 quality strategies via Optional-Effect Injection.

    Each strategy slot accepts ``None``; the composite still implements
    :class:`QualityCheckProposalService` and returns an empty proposal
    list when every strategy is ``None`` (pure no-op — the Compounding
    factory surfaces this as zero proposed checks, identical to
    "service not wired").

    Doctrine: Optional-Effect Injection (case 10 — L7 quality discovery,
    parallel to case 9's L3 lineage discovery). The factory composes by
    passing ``None`` for any strategy that's not enabled in the current
    deployment; per-strategy telemetry counters in :meth:`metrics` make
    the chosen path auditable per Rule 9.

    Strategy execution order: ``dbt_tests → schema_pattern →
    historical_stats`` (highest-confidence first — though all three
    always run when configured; the order only fixes encounter order
    in the composite reasoning string for replay stability).

    Implementation: composes a :class:`LakeLoopComposite` (the shared
    generic) with L7-specific case-name (``"quality_inference"``),
    propose-method (``"propose_checks"``), identity-key (``check_id``),
    and a defensive merge-cluster hook that re-hashes the head canonical
    id to catch hash-contract drift.
    """

    name: str = "composite"

    def __init__(
        self,
        *,
        schema_pattern: SchemaPatternStrategy | None = None,
        dbt_tests: DbtTestsStrategy | None = None,
        historical_stats: HistoricalStatsStrategy | None = None,
        semantic_type: SemanticTypeQualityCheckStrategy | None = None,
    ) -> None:
        self.schema_pattern = schema_pattern
        self.dbt_tests = dbt_tests
        self.historical_stats = historical_stats
        # 4th strategy — the L5→L7 cross-axis chain. Additive Optional-
        # Effect Injection slot; default None preserves byte-identical
        # pre-cross-axis composite behaviour for all existing tests.
        self.semantic_type = semantic_type

        # Strategy ordering pinned by tests: dbt_tests first → schema_pattern
        # → historical_stats → semantic_type. The cross-axis strategy
        # runs last so its reasoning string slot sits at the tail of the
        # composite-merged reasoning when multiple strategies converge
        # on the same check_id; existing test_composite_merge_dedup_*
        # assertions stay unaffected.
        self._composite: LakeLoopComposite[
            ProposedQualityCheck
        ] = LakeLoopComposite[ProposedQualityCheck](
            case_name="quality_inference",
            strategies={
                "dbt_tests": dbt_tests,
                "schema_pattern": schema_pattern,
                "historical_stats": historical_stats,
                "semantic_type": semantic_type,
            },
            propose_method="propose_checks",
            identity_key=_check_identity,
            proposals_counter_name="checks_proposed",
            merge_cluster=_merge_quality_cluster,
        )

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """Run all configured strategies; merge + dedup by check_id.

        ``company_id`` is forwarded to every strategy (the existing 3
        ignore it; the new ``semantic_type`` strategy needs it to scope
        its cross-axis L5 read by tenant). Default ``None`` preserves
        byte-identical pre-cross-axis caller behaviour.
        """
        return await self._composite.propose(
            table=table, sample_size=sample_size, company_id=company_id,
        )

    def metrics(self) -> dict[str, int]:
        """Per-strategy telemetry counters per Optional-Effect doctrine Rule 9.

        Keys (byte-identical to the pre-extraction shape):

          * ``quality_inference_invocations`` — total composite calls.
          * ``quality_inference_strategy_invocations.<name>`` — per-
            strategy fire count. Zero for ``None`` strategies.
          * ``quality_inference_checks_proposed`` — total merged
            proposals returned across all invocations.
          * ``quality_inference_no_op`` — invocations where all
            strategies were ``None`` (Optional-Effect absent path).
        """
        return self._composite.metrics()
