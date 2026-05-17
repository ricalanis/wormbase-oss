"""Generic composite over N independently-None strategies for lake-side L-axes.

:class:`LakeLoopComposite` is the extracted shared shape behind L3
:class:`~wormbase_agent_gateway.lineage.CompositeLineageInferenceService`,
L7 :class:`~wormbase_agent_gateway.quality.CompositeQualityProposalService`,
and L4 :class:`~wormbase_agent_gateway.schema_impact.CompositeSchemaImpactService`.

The OptionalEffectGuard precedent — *extract when the 3rd consumer
ships* — fired on the L4 close-out (HEAD = ``d80b076``). Before this
module, each axis carried a near-identical ~80-LOC composite class plus
a ~40-LOC ``_merge_proposals`` helper. The composite contract is:

  * Accept N strategies, each independently ``None``.
  * Run all non-None strategies in axis-configured order.
  * Cluster results by axis-configured identity key.
  * Merge clusters via axis-configured merge winner (default: max
    confidence) + structural fields (reasoning concatenation, evidence
    keyed by strategy name, ``strategy="composite"`` when >1 distinct).
  * Track per-strategy + total telemetry counters with axis-namespaced
    keys (e.g. ``lineage_inference_invocations``).

Doctrine: Optional-Effect Injection cases 9/10/11. The factory composes
by passing ``None`` for any strategy not enabled in the current
deployment; per-strategy telemetry counters make the chosen path
auditable per Rule 9.

Per-axis specialisations stay axis-side:

  * Each axis ships a thin builder function (e.g.
    :func:`~wormbase_agent_gateway.lineage.composite.CompositeLineageInferenceService`)
    that supplies the case-name, strategy ordering, merge-winner hook,
    and counter-key prefix.
  * Ledger payloads, projection schemas, dashboard pages, server
    actions stay duplicated by design (axis-specific semantics that
    don't share cleanly).

This composite is **strictly internal infrastructure**; tests pin its
contract through the existing per-axis composite tests
(``test_lineage_composite.py``, ``test_quality_composite.py``,
``test_schema_impact_composite.py``) plus a dedicated generic-shape
suite (``test_lake_loop_composite.py``).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass, replace
from typing import Any, Generic, TypeVar

from .protocol import LakeLoopProposal

__all__ = [
    "LakeLoopComposite",
    "default_cluster_merge",
    "default_merge_winner",
]

T = TypeVar("T", bound=LakeLoopProposal)


def default_merge_winner(a: T, b: T) -> T:
    """Default tie-breaker: highest ``confidence`` wins; ``a`` on ties."""
    return a if a.confidence >= b.confidence else b


def default_cluster_merge(
    proposals: list[T],
    *,
    merge_winner: Callable[[T, T], T] = default_merge_winner,
) -> T:
    """Default merge for a cluster of proposals sharing the same identity.

    Contract (matches the three pre-extraction axes byte-identically):

      * Single-proposal short-circuit — return the proposal verbatim so
        single-strategy clusters keep their native ``strategy`` label
        instead of being wrapped as ``"composite"``.
      * Winner selection — fold over ``merge_winner`` (default: max
        confidence).
      * ``strategy`` — ``"composite"`` when >1 distinct strategies
        contributed, else the single strategy name.
      * ``reasoning`` — ``"; "``-joined in encounter order.
      * ``evidence`` — dict keyed by strategy name; each strategy's
        original evidence at ``evidence[<strategy>]``.

    Used as :class:`LakeLoopComposite`'s default ``merge_cluster`` hook.
    Axes that need extra field-level merge logic (e.g. L7's ``config``
    selection or L4's ``upstream_lineage_edge_id`` threading) pass a
    custom hook to the composite.

    Requires ``T`` to be a frozen :func:`dataclasses.dataclass` because
    we use :func:`dataclasses.replace` to mint the merged result while
    preserving any extra fields the axis carries (e.g. ``edge_id``,
    ``table_id``, ``upstream_lineage_edge_id``).
    """
    assert proposals, "must have at least one proposal to merge"

    if len(proposals) == 1:
        return proposals[0]

    if not is_dataclass(proposals[0]):
        msg = (
            f"default_cluster_merge requires dataclass proposals; "
            f"got {type(proposals[0]).__name__!r}. Pass a custom "
            f"merge_cluster hook for non-dataclass proposal types."
        )
        raise TypeError(msg)

    winner: T = proposals[0]
    for p in proposals[1:]:
        winner = merge_winner(winner, p)

    distinct_strategies = {p.strategy for p in proposals}
    strategy = (
        "composite"
        if len(distinct_strategies) > 1
        else next(iter(distinct_strategies))
    )
    reasoning = "; ".join(p.reasoning for p in proposals)
    evidence: dict[str, Any] = {}
    for p in proposals:
        evidence[p.strategy] = p.evidence

    return replace(
        winner,
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


class LakeLoopComposite(Generic[T]):
    """Generic composite over N independently-None strategies.

    Captures the shape of the three lake-side composites: L3 lineage
    discovery (case 9), L7 quality-check discovery (case 10), L4
    schema-evolution-impact (case 11). Doctrine case templated.

    Constructor:

      * ``case_name`` — telemetry counter key prefix (e.g.
        ``"lineage_inference"`` → ``"lineage_inference_invocations"``,
        ``"lineage_inference_strategy_invocations.<name>"``, etc.).
      * ``strategies`` — ordered dict (insertion order = strategy
        execution order) mapping strategy slot name → strategy instance
        or ``None``. The slot name is used as the per-strategy
        telemetry counter suffix AND as the dedup key for collisions
        with same-slot retries.
      * ``propose_method`` — method name to invoke on each strategy
        (``"infer_edges"`` for L3, ``"propose_checks"`` for L7,
        ``"propose_impacts"`` for L4).
      * ``identity_key`` — callable extracting the dedup key from a
        proposal (e.g. ``lambda e: e.edge_id``). Proposals sharing an
        identity key from multiple strategies fold into one merged
        proposal via ``merge_cluster``.
      * ``proposals_counter_name`` — axis-specific counter name for the
        "proposals emitted" total (e.g. ``"edges_proposed"`` for L3,
        ``"checks_proposed"`` for L7, ``"impacts_proposed"`` for L4).
        Full key is ``f"{case_name}_{proposals_counter_name}"``.
      * ``merge_cluster`` — callable that folds a list of same-identity
        proposals into one merged proposal. Default:
        :func:`default_cluster_merge`. Axes that need extra field-level
        merge logic pass a custom hook.

    The composite is itself a per-axis service (e.g. a
    :class:`~wormbase_agent_gateway.lineage.LineageInferenceService`) by
    virtue of exposing a single method ``propose(**kwargs)`` that
    dispatches to all wired strategies. Per-axis builders typically
    expose the result via a thin wrapper that aliases ``propose`` to
    the axis-specific method name (``infer_edges`` / ``propose_checks``
    / ``propose_impacts``).
    """

    name: str = "composite"

    def __init__(
        self,
        *,
        case_name: str,
        strategies: dict[str, Any | None],
        propose_method: str,
        identity_key: Callable[[T], str],
        proposals_counter_name: str,
        merge_cluster: Callable[[list[T]], T] = default_cluster_merge,
        min_confidence: float | None = None,
    ) -> None:
        self._case_name = case_name
        # Preserve insertion order — strategy execution order is axis-
        # specific and pinned by tests (see e.g.
        # test_lineage_composite::test_composite_merge_dedup_highest_confidence_wins
        # which depends on naming firing before sample_overlap so the
        # reasoning string starts with "naming match").
        self._strategies: dict[str, Any | None] = dict(strategies)
        self._propose_method = propose_method
        self._identity_key = identity_key
        self._proposals_counter_name = proposals_counter_name
        self._merge_cluster = merge_cluster
        # Composite-level promotion-time floor. When None (default), no
        # filtering happens — back-compat for L3/L7 callers that don't
        # wire a knob. When set, proposals with ``confidence <
        # min_confidence`` are dropped POST-merge so per-strategy raw
        # signals still flow to the cluster (the merged-winner
        # confidence is what gets compared, not each contributing
        # strategy's raw confidence) and per-strategy telemetry stays
        # accurate.
        self._min_confidence: float | None = min_confidence

        # Per Rule 9 — counters auditable from the outside.
        self._invocations: int = 0
        # Per-slot fire counter; key matches the slot name passed in
        # the strategies dict so the metrics view stays symmetric.
        self._slot_invocations: dict[str, int] = {
            name: 0 for name in self._strategies
        }
        self._proposals_emitted: int = 0
        self._no_op_invocations: int = 0
        # Promotion-time filter telemetry — count of proposals dropped
        # below the min_confidence floor. Always tracked; the counter
        # stays zero when no floor is wired.
        self._below_min_confidence_dropped: int = 0

    @property
    def case_name(self) -> str:
        """Telemetry counter key prefix — useful for axis-side assertions."""
        return self._case_name

    @property
    def strategies(self) -> dict[str, Any | None]:
        """Read-only view of strategy slots — useful for axis-side debug."""
        return dict(self._strategies)

    async def propose(self, **kwargs: Any) -> list[T]:
        """Run all configured strategies; merge + dedup by ``identity_key``.

        Calls ``getattr(strategy, self._propose_method)(**kwargs)`` for
        every non-None strategy in declaration order. Clusters results
        by ``identity_key``; folds each cluster via ``merge_cluster``.

        Returns ``[]`` and increments ``no_op`` when ALL strategies are
        ``None`` (the pure Optional-Effect-absent path). When strategies
        are wired but each returns ``[]``, returns ``[]`` WITHOUT
        incrementing ``no_op`` (no_op is reserved for the all-None
        path per the doctrine; see
        ``test_quality_composite::test_composite_no_proposals_returns_empty_without_no_op_increment``).
        """
        self._invocations += 1

        by_id: dict[str, list[T]] = {}

        for slot_name, strategy in self._strategies.items():
            if strategy is None:
                continue
            self._slot_invocations[slot_name] += 1
            method = getattr(strategy, self._propose_method)
            proposals = await method(**kwargs)
            for p in proposals:
                by_id.setdefault(self._identity_key(p), []).append(p)

        if not by_id:
            # No-op only when EVERY strategy is None.
            if all(s is None for s in self._strategies.values()):
                self._no_op_invocations += 1
            return []

        merged: list[T] = []
        for cluster in by_id.values():
            merged.append(self._merge_cluster(cluster))

        # Apply composite-level min_confidence floor (when wired).
        # POST-merge filtering preserves per-strategy telemetry — each
        # strategy still fires, returns proposals, and the merged
        # winner's confidence is the threshold-relevant value. Dropped
        # proposals are counted via _below_min_confidence_dropped so
        # promotion-rate is auditable per Rule 9.
        if self._min_confidence is not None:
            filtered: list[T] = []
            for proposal in merged:
                if proposal.confidence < self._min_confidence:
                    self._below_min_confidence_dropped += 1
                else:
                    filtered.append(proposal)
            merged = filtered

        self._proposals_emitted += len(merged)
        return merged

    def metrics(self) -> dict[str, int]:
        """Per-strategy telemetry counters per Optional-Effect doctrine Rule 9.

        Keys (axis-namespaced via ``case_name``):

          * ``{case_name}_invocations`` — total composite calls.
          * ``{case_name}_strategy_invocations.<slot_name>`` — per-slot
            fire count. Zero for ``None`` slots.
          * ``{case_name}_{proposals_counter_name}`` — total merged
            proposals returned across all invocations.
          * ``{case_name}_no_op`` — invocations where ALL strategies
            were ``None`` (the Optional-Effect-absent path).

        Counter keys are byte-identical to the pre-extraction per-axis
        composites; tests pinning the exact key strings (e.g.
        ``test_lineage_composite::test_composite_all_none_returns_empty_and_counts_no_op``)
        keep passing unchanged.
        """
        out: dict[str, int] = {
            f"{self._case_name}_invocations": self._invocations,
        }
        for slot_name, count in self._slot_invocations.items():
            out[
                f"{self._case_name}_strategy_invocations.{slot_name}"
            ] = count
        out[
            f"{self._case_name}_{self._proposals_counter_name}"
        ] = self._proposals_emitted
        out[f"{self._case_name}_no_op"] = self._no_op_invocations
        # Below-min-confidence drop counter. Always emitted; stays at
        # zero when no min_confidence floor is wired. Per Rule 9, the
        # gate's effect on promotion-rate must be auditable from the
        # outside.
        out[
            f"{self._case_name}_below_min_confidence_dropped"
        ] = self._below_min_confidence_dropped
        return out
