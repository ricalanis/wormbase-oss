"""Unit tests for the ``Compounding`` W5a Reactivity primitive.

v2.B Phase 1 introduced ``Compounding`` as the parameterised primitive
that closes journey-revision Seam #4. The two existing Reactivities
(``OutcomeToTemplatePromotionReactivity`` +
``QueryOutcomeToDataProductReactivity``) are thin subclasses of it; this
test exercises the primitive itself on synthetic clusters so its
behaviour is pinned independently of those two real-world factories.

Phase 2 will compose three new axes (failures-as-bad-patterns,
gaps-as-escalations, consumption-as-recommendations) using plain
``Compounding(...)`` instances — these unit tests are the durable
contract those new axes inherit.

Each test isolates one branch of the pipeline:

  * source_predicate gate via EntryKind match (skipped — Compounding
    relies on the W5a runner having already matched; behaviour with
    arbitrary entries is the relevant axis, not the predicate)
  * quality_filter short-circuit
  * gather_fn called with (entry, ctx); its output reaches cluster_fn
  * promotion_threshold filters clusters
  * promotion_action called once per passing cluster
  * promotion_action returning None signals idempotent suppression
  * novelty_key callable resolves per-entry; static str also works
  * condition (NotRecentlyFired) does not gate inside fire() — the
    W5a runner evaluates the condition; the primitive only consumes
    novelty_key for the runner's post-fire bookkeeping
  * Distinct parameterisations produce distinct behaviour (smoke test)
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from wormbase_reactivities.conditions import NotRecentlyFired
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityContext,
)

from wormbase_agent_gateway.reactivities import Compounding


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000000c1")


def _make_outcome_entry(
    *, score: str = "0.95", used: bool = True, useful: bool = True,
    nl: str = "test question?",
    extra: dict[str, Any] | None = None,
    entry_id: str = "00000000-0000-0000-0000-000000000aaa",
) -> dict[str, Any]:
    """Synthesize a canonical query_outcome_recorded execute entry."""
    args = {
        "agent_query_id": "aq-1",
        "nl_question": nl,
        "final_query_spec": {"domain_id": "dom-x"},
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "user_correction": None,
        "quality_score": score,
    }
    if extra:
        args.update(extra)
    return {
        "kind": "execute",
        "entry_id": entry_id,
        "seq": 1,
        "ts": datetime.now(UTC),
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": args,
            "result_ref": "aq-1",
        },
    }


def _make_ctx(ledger: Any = None) -> ReactivityContext:
    """Build a ReactivityContext with a frozen ``now`` and a duck ledger."""
    return ReactivityContext(
        ledger=ledger,
        company_id=_COMPANY_ID,
        registry=None,
        now=lambda: datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        extras={"reactivity_id": "test_compounding"},
    )


# ---------------------------------------------------------------------------
# 1. quality_filter short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_filter_false_short_circuits_pipeline() -> None:
    """If quality_filter returns False, gather_fn / cluster_fn /
    promotion_action are never called."""
    gather = AsyncMock(return_value=[])
    action = AsyncMock()

    primitive = Compounding(
        id="test.quality_filter",
        name="test.quality_filter",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _payload: False,
        gather_fn=gather,
        cluster_fn=lambda entries: [list(entries)],
        promotion_threshold=lambda c: len(c) >= 1,
        promotion_action=action,
    )

    result = await primitive.fire(_make_outcome_entry(), _make_ctx())

    assert result.fired is False
    assert result.actions == []
    gather.assert_not_awaited()
    action.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2. gather_fn output reaches cluster_fn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_fn_output_reaches_cluster_fn() -> None:
    """The synchronous cluster_fn receives whatever gather_fn returned."""
    gathered = [
        _make_outcome_entry(entry_id="00000000-0000-0000-0000-000000000001"),
        _make_outcome_entry(entry_id="00000000-0000-0000-0000-000000000002"),
    ]
    received_by_cluster: list[Sequence[dict[str, Any]]] = []

    async def gather(_e: dict[str, Any], _ctx: ReactivityContext) -> Sequence[dict[str, Any]]:
        return gathered

    def cluster(entries: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        received_by_cluster.append(entries)
        return [list(entries)]

    primitive = Compounding(
        id="test.gather",
        name="test.gather",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=gather,
        cluster_fn=cluster,
        promotion_threshold=lambda c: False,  # block promotion to focus on gather→cluster
        promotion_action=AsyncMock(),
    )

    await primitive.fire(_make_outcome_entry(), _make_ctx())

    assert len(received_by_cluster) == 1
    assert list(received_by_cluster[0]) == gathered


# ---------------------------------------------------------------------------
# 3. promotion_action called per cluster passing threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotion_action_called_per_passing_cluster() -> None:
    """promotion_action runs once per cluster that satisfies threshold;
    clusters under threshold are skipped."""
    # 3 synthetic clusters: 2 above threshold-2, 1 below.
    clusters = [
        [{"id": "a"}, {"id": "b"}],
        [{"id": "c"}],                  # below threshold
        [{"id": "d"}, {"id": "e"}, {"id": "f"}],
    ]
    call_log: list[list[dict[str, Any]]] = []

    async def action(
        cluster: list[dict[str, Any]], _ctx: ReactivityContext,
    ) -> FiredAction | None:
        call_log.append(cluster)
        return FiredAction(action_kind="synthetic_promoted")

    primitive = Compounding(
        id="test.threshold",
        name="test.threshold",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[]),
        cluster_fn=lambda _e: clusters,
        promotion_threshold=lambda c: len(c) >= 2,
        promotion_action=action,
    )

    result = await primitive.fire(_make_outcome_entry(), _make_ctx())

    # 2 clusters passed threshold; 2 actions invoked.
    assert len(call_log) == 2
    assert result.fired is True
    assert len(result.actions) == 2
    assert all(a.action_kind == "synthetic_promoted" for a in result.actions)


# ---------------------------------------------------------------------------
# 4. promotion_action returning None signals idempotent suppression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotion_action_returning_none_suppresses_fire() -> None:
    """When promotion_action returns None for every cluster, ReactivityResult.fired is False."""
    async def suppressed_action(
        _cluster: list[dict[str, Any]], _ctx: ReactivityContext,
    ) -> FiredAction | None:
        return None

    primitive = Compounding(
        id="test.idempotent",
        name="test.idempotent",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[{"id": "x"}]),
        cluster_fn=lambda entries: [list(entries)],
        promotion_threshold=lambda _c: True,
        promotion_action=suppressed_action,
    )

    result = await primitive.fire(_make_outcome_entry(), _make_ctx())

    assert result.fired is False
    assert result.actions == []


# ---------------------------------------------------------------------------
# 5. novelty_key — static + callable resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_novelty_key_static_string_propagates_to_result() -> None:
    primitive = Compounding(
        id="test.novelty_static",
        name="test.novelty_static",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[{"id": "x"}]),
        cluster_fn=lambda entries: [list(entries)],
        promotion_threshold=lambda _c: True,
        promotion_action=AsyncMock(return_value=FiredAction(action_kind="k")),
        novelty_key="static_key",
    )

    result = await primitive.fire(_make_outcome_entry(), _make_ctx())
    assert result.novelty_key == "static_key"


@pytest.mark.asyncio
async def test_novelty_key_callable_resolves_per_entry() -> None:
    """A callable novelty_key derives a per-fire key from the triggering entry.

    This is the contract per-outcome Reactivities use so the per-Reactivity
    debounce doesn't collide across distinct originators.
    """
    primitive = Compounding(
        id="test.novelty_dyn",
        name="test.novelty_dyn",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[]),
        cluster_fn=lambda _e: [],
        promotion_threshold=lambda _c: False,
        promotion_action=AsyncMock(),
        novelty_key=lambda entry: (
            f"k:{(entry.get('payload') or {}).get('args', {}).get('agent_query_id', 'none')}"
        ),
    )

    entry = _make_outcome_entry(extra={"agent_query_id": "aq-42"})
    result = await primitive.fire(entry, _make_ctx())
    assert result.novelty_key == "k:aq-42"


# ---------------------------------------------------------------------------
# 6. Optional condition collapses to AlwaysAllow; explicit override wired through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_condition_is_always_allow() -> None:
    """No explicit condition -> Compounding.condition.allows() returns True."""
    primitive = Compounding(
        id="test.always_allow",
        name="test.always_allow",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[]),
        cluster_fn=lambda _e: [],
        promotion_threshold=lambda _c: False,
        promotion_action=AsyncMock(),
    )

    ctx = _make_ctx()
    allowed = await primitive.condition.allows(_make_outcome_entry(), ctx)
    assert allowed is True


@pytest.mark.asyncio
async def test_condition_override_wired_to_self_condition() -> None:
    """Constructor's _condition_override flows to the Reactivity.condition slot.

    The W5a runner reads ``r.condition.allows(entry, ctx)`` before
    invoking ``r.fire``. Pinning that the override slot reaches
    ``self.condition`` proves the Compounding instance is a drop-in
    Reactivity from the runner's perspective.
    """
    override = NotRecentlyFired(novelty_key="custom_key", hours=2.5)
    primitive = Compounding(
        id="test.condition_override",
        name="test.condition_override",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[]),
        cluster_fn=lambda _e: [],
        promotion_threshold=lambda _c: False,
        promotion_action=AsyncMock(),
        _condition_override=override,
    )

    assert primitive.condition is override


# ---------------------------------------------------------------------------
# 7. Distinct parameterisations produce distinct behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_parameterisations_produce_different_behaviour() -> None:
    """Smoke test: a cluster-axis instance and a per-entry-axis instance
    produce different action counts on the same entry stream.

    Pins that Compounding is a true primitive — behaviour is driven by
    parameters, not by class identity. Phase 2's three new axes will
    reuse this exact pattern.
    """
    # Cluster axis: cluster by `nl_question`, threshold 2.
    def cluster_by_nl(entries: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            nl = ((e.get("payload") or {}).get("args") or {}).get("nl_question") or ""
            groups.setdefault(nl, []).append(e)
        return list(groups.values())

    cluster_action = AsyncMock(return_value=FiredAction(action_kind="clustered"))
    cluster_primitive = Compounding(
        id="test.cluster",
        name="test.cluster",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[
            _make_outcome_entry(nl="alpha"),
            _make_outcome_entry(nl="alpha"),
            _make_outcome_entry(nl="beta"),
        ]),
        cluster_fn=cluster_by_nl,
        promotion_threshold=lambda c: len(c) >= 2,
        promotion_action=cluster_action,
    )

    # Per-entry axis: identity cluster, threshold 1.
    per_entry_action = AsyncMock(return_value=FiredAction(action_kind="per_entry"))
    per_entry_primitive = Compounding(
        id="test.per_entry",
        name="test.per_entry",
        description="-",
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=lambda _p: True,
        gather_fn=AsyncMock(return_value=[
            _make_outcome_entry(nl="alpha"),
            _make_outcome_entry(nl="alpha"),
            _make_outcome_entry(nl="beta"),
        ]),
        cluster_fn=lambda entries: [[e] for e in entries],
        promotion_threshold=lambda c: len(c) >= 1,
        promotion_action=per_entry_action,
    )

    cluster_result = await cluster_primitive.fire(_make_outcome_entry(), _make_ctx())
    per_entry_result = await per_entry_primitive.fire(_make_outcome_entry(), _make_ctx())

    # Cluster axis: only the 2-element "alpha" cluster passes threshold.
    assert cluster_action.await_count == 1
    assert len(cluster_result.actions) == 1
    assert cluster_result.actions[0].action_kind == "clustered"

    # Per-entry axis: all 3 entries cross the threshold.
    assert per_entry_action.await_count == 3
    assert len(per_entry_result.actions) == 3
    assert all(a.action_kind == "per_entry" for a in per_entry_result.actions)
