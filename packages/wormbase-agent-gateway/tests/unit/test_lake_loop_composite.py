"""Tests for the shared :class:`LakeLoopComposite` generic.

Pins:

  * Counter-key shape (axis-namespaced via ``case_name``).
  * Per-slot None-ability + all-None no-op semantics.
  * Strategy execution order preserved (dict insertion order).
  * Cluster dedup via ``identity_key``.
  * Default merge winner (max confidence; first on ties).
  * Default cluster merge (single-strategy short-circuit; composite
    strategy label on >1 distinct; reasoning concatenation; evidence
    keyed by strategy).
  * Custom ``merge_cluster`` hook honoured.
  * Per-strategy counters fire even when the strategy returns ``[]``.
  * Empty results from wired strategies don't trip the no_op counter.

These tests live alongside the per-axis composite tests but exercise
the generic directly via lightweight fake-strategy dataclasses, so any
regression on the shared generic surfaces here independent of the
axis-specific test suites.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from wormbase_agent_gateway.lake_loop import (
    LakeLoopComposite,
    default_cluster_merge,
    default_merge_winner,
)


# ---------------------------------------------------------------------------
# Fake proposal + strategy types — minimal shape that satisfies the
# LakeLoopProposal Protocol (confidence + strategy + reasoning + evidence)
# plus an identity field used as the cluster key.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeProposal:
    """Minimal proposal type for generic-composite tests."""

    proposal_id: str
    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any] = field(default_factory=dict)


class _FakeStrategy:
    """Async strategy with a configurable ``propose`` method name."""

    def __init__(
        self,
        *,
        name: str,
        results: list[_FakeProposal] | None = None,
        propose_method: str = "propose",
    ) -> None:
        self.name = name
        self._results = list(results or [])
        self.call_count = 0
        self.last_kwargs: dict[str, Any] = {}
        # Bind the propose method under the configured name so the
        # composite can call ``getattr(self, propose_method)(...)``.
        setattr(self, propose_method, self._propose)

    async def _propose(self, **kwargs: Any) -> list[_FakeProposal]:
        self.call_count += 1
        self.last_kwargs = dict(kwargs)
        return list(self._results)


def _proposal(
    pid: str = "p1",
    confidence: float = 0.5,
    strategy: str = "fake",
    reasoning: str = "fake reason",
    evidence: dict[str, Any] | None = None,
) -> _FakeProposal:
    return _FakeProposal(
        proposal_id=pid,
        confidence=confidence,
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence or {"value": 1},
    )


def _make_composite(
    strategies: dict[str, _FakeStrategy | None],
    *,
    case_name: str = "fake_axis",
    proposals_counter_name: str = "proposals_emitted",
    propose_method: str = "propose",
    merge_cluster=default_cluster_merge,
    min_confidence: float | None = None,
) -> LakeLoopComposite[_FakeProposal]:
    return LakeLoopComposite[_FakeProposal](
        case_name=case_name,
        strategies=strategies,
        propose_method=propose_method,
        identity_key=lambda p: p.proposal_id,
        proposals_counter_name=proposals_counter_name,
        merge_cluster=merge_cluster,
        min_confidence=min_confidence,
    )


# ---------------------------------------------------------------------------
# Counter shape + axis-namespacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_keys_use_case_name_prefix() -> None:
    """All counter keys are prefixed with ``case_name``."""
    composite = _make_composite(
        strategies={"alpha": None, "beta": None},
        case_name="custom_axis",
        proposals_counter_name="things_made",
    )
    await composite.propose()
    metrics = composite.metrics()
    assert "custom_axis_invocations" in metrics
    assert "custom_axis_strategy_invocations.alpha" in metrics
    assert "custom_axis_strategy_invocations.beta" in metrics
    assert "custom_axis_things_made" in metrics
    assert "custom_axis_no_op" in metrics
    # No bare/unnamed keys
    assert all(k.startswith("custom_axis_") for k in metrics)


# ---------------------------------------------------------------------------
# No-op semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_none_triggers_no_op_counter() -> None:
    """All strategy slots None → empty result + no_op counter increments."""
    composite = _make_composite(strategies={"alpha": None, "beta": None})
    result = await composite.propose()
    assert result == []
    metrics = composite.metrics()
    assert metrics["fake_axis_invocations"] == 1
    assert metrics["fake_axis_no_op"] == 1
    assert metrics["fake_axis_proposals_emitted"] == 0
    assert metrics["fake_axis_strategy_invocations.alpha"] == 0
    assert metrics["fake_axis_strategy_invocations.beta"] == 0


@pytest.mark.asyncio
async def test_wired_strategies_returning_empty_do_not_trigger_no_op() -> None:
    """Strategies wired but return [] → no_op does NOT fire (reserved for all-None)."""
    composite = _make_composite(
        strategies={"alpha": _FakeStrategy(name="alpha", results=[])},
    )
    result = await composite.propose()
    assert result == []
    metrics = composite.metrics()
    assert metrics["fake_axis_strategy_invocations.alpha"] == 1
    assert metrics["fake_axis_no_op"] == 0
    assert metrics["fake_axis_proposals_emitted"] == 0


# ---------------------------------------------------------------------------
# Per-slot counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_configured_slot_increments_its_counter() -> None:
    """One slot set, others None → only the set slot's counter increments."""
    alpha = _FakeStrategy(name="alpha", results=[_proposal()])
    composite = _make_composite(
        strategies={"alpha": alpha, "beta": None, "gamma": None},
    )
    await composite.propose()
    metrics = composite.metrics()
    assert metrics["fake_axis_strategy_invocations.alpha"] == 1
    assert metrics["fake_axis_strategy_invocations.beta"] == 0
    assert metrics["fake_axis_strategy_invocations.gamma"] == 0
    assert metrics["fake_axis_no_op"] == 0


@pytest.mark.asyncio
async def test_counters_accumulate_across_invocations() -> None:
    """Per-strategy + total counters accumulate across calls."""
    alpha = _FakeStrategy(name="alpha", results=[_proposal()])
    composite = _make_composite(strategies={"alpha": alpha})
    for _ in range(3):
        await composite.propose()
    metrics = composite.metrics()
    assert metrics["fake_axis_invocations"] == 3
    assert metrics["fake_axis_strategy_invocations.alpha"] == 3
    assert metrics["fake_axis_proposals_emitted"] == 3


# ---------------------------------------------------------------------------
# Strategy execution order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_order_follows_dict_insertion_order() -> None:
    """Strategies are called in the dict insertion order."""
    call_order: list[str] = []

    class _OrderingStrategy:
        def __init__(self, name: str) -> None:
            self.name = name

        async def propose(self, **_kwargs: Any) -> list[_FakeProposal]:
            call_order.append(self.name)
            return [_proposal(pid=self.name, strategy=self.name)]

    composite = LakeLoopComposite[_FakeProposal](
        case_name="ordering",
        # Insertion order: c → a → b
        strategies={
            "c": _OrderingStrategy("c"),
            "a": _OrderingStrategy("a"),
            "b": _OrderingStrategy("b"),
        },
        propose_method="propose",
        identity_key=lambda p: p.proposal_id,
        proposals_counter_name="things",
    )
    await composite.propose()
    assert call_order == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Identity-key dedup + merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proposals_with_distinct_ids_stay_separate() -> None:
    """Two strategies, each emitting a unique identity → 2 results returned."""
    alpha = _FakeStrategy(
        name="alpha", results=[_proposal(pid="p1", strategy="alpha")],
    )
    beta = _FakeStrategy(
        name="beta", results=[_proposal(pid="p2", strategy="beta")],
    )
    composite = _make_composite(strategies={"alpha": alpha, "beta": beta})
    result = await composite.propose()
    assert len(result) == 2
    assert {r.proposal_id for r in result} == {"p1", "p2"}
    # Each kept its native strategy label (no merge)
    assert {r.strategy for r in result} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_proposals_with_same_id_are_merged() -> None:
    """Two strategies emitting the same identity → one merged proposal."""
    alpha = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(
                pid="shared",
                confidence=0.7,
                strategy="alpha",
                reasoning="alpha reason",
                evidence={"a": 1},
            ),
        ],
    )
    beta = _FakeStrategy(
        name="beta",
        results=[
            _proposal(
                pid="shared",
                confidence=0.9,
                strategy="beta",
                reasoning="beta reason",
                evidence={"b": 2},
            ),
        ],
    )
    composite = _make_composite(strategies={"alpha": alpha, "beta": beta})
    result = await composite.propose()
    assert len(result) == 1
    merged = result[0]
    # Max-confidence winner
    assert merged.confidence == 0.9
    # Distinct strategies → composite label
    assert merged.strategy == "composite"
    # Reasoning concatenation in encounter order (alpha first)
    assert merged.reasoning == "alpha reason; beta reason"
    # Evidence keyed by strategy name
    assert merged.evidence == {"alpha": {"a": 1}, "beta": {"b": 2}}


@pytest.mark.asyncio
async def test_single_strategy_short_circuit_keeps_native_label() -> None:
    """Single contributor → returned verbatim with native strategy label."""
    alpha = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(
                pid="solo",
                confidence=0.4,
                strategy="alpha",
                reasoning="alpha reason",
            ),
        ],
    )
    composite = _make_composite(strategies={"alpha": alpha})
    result = await composite.propose()
    assert len(result) == 1
    assert result[0].strategy == "alpha"
    assert result[0].reasoning == "alpha reason"


# ---------------------------------------------------------------------------
# Default merge winner — tie-breaking
# ---------------------------------------------------------------------------


def test_default_merge_winner_picks_higher_confidence() -> None:
    a = _proposal(pid="x", confidence=0.3, strategy="a")
    b = _proposal(pid="x", confidence=0.7, strategy="b")
    assert default_merge_winner(a, b) is b
    assert default_merge_winner(b, a) is b


def test_default_merge_winner_breaks_ties_with_first() -> None:
    a = _proposal(pid="x", confidence=0.5, strategy="a")
    b = _proposal(pid="x", confidence=0.5, strategy="b")
    assert default_merge_winner(a, b) is a


# ---------------------------------------------------------------------------
# Custom merge_cluster hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_merge_cluster_is_honoured() -> None:
    """A custom merge_cluster hook fully replaces the default merger."""
    merge_calls: list[int] = []

    def _custom_merge(proposals: list[_FakeProposal]) -> _FakeProposal:
        merge_calls.append(len(proposals))
        # Always emit a sentinel with a marker strategy
        return _proposal(
            pid="custom",
            confidence=1.0,
            strategy="custom_merger",
            reasoning="custom",
            evidence={"clustered_count": len(proposals)},
        )

    alpha = _FakeStrategy(
        name="alpha", results=[_proposal(pid="shared", strategy="alpha")],
    )
    beta = _FakeStrategy(
        name="beta", results=[_proposal(pid="shared", strategy="beta")],
    )
    composite = _make_composite(
        strategies={"alpha": alpha, "beta": beta},
        merge_cluster=_custom_merge,
    )
    result = await composite.propose()
    assert len(result) == 1
    assert result[0].strategy == "custom_merger"
    assert result[0].evidence == {"clustered_count": 2}
    # Custom hook called once per cluster (here: 1 cluster of 2)
    assert merge_calls == [2]


# ---------------------------------------------------------------------------
# propose_method dispatching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_method_dispatches_to_named_attribute() -> None:
    """``propose_method`` selects which strategy method the composite calls."""
    alpha = _FakeStrategy(
        name="alpha", results=[_proposal()], propose_method="infer_things",
    )
    composite = _make_composite(
        strategies={"alpha": alpha}, propose_method="infer_things",
    )
    result = await composite.propose(arg1="hello", arg2=42)
    assert len(result) == 1
    # Strategy's bound method was invoked once with the kwargs
    assert alpha.call_count == 1
    assert alpha.last_kwargs == {"arg1": "hello", "arg2": 42}


@pytest.mark.asyncio
async def test_propose_threads_kwargs_to_each_strategy() -> None:
    """All non-None strategies receive the same kwargs."""
    alpha = _FakeStrategy(name="alpha", results=[_proposal(pid="a")])
    beta = _FakeStrategy(name="beta", results=[_proposal(pid="b")])
    composite = _make_composite(strategies={"alpha": alpha, "beta": beta})
    await composite.propose(table_id="orders", sample_size=500)
    assert alpha.last_kwargs == {"table_id": "orders", "sample_size": 500}
    assert beta.last_kwargs == {"table_id": "orders", "sample_size": 500}


# ---------------------------------------------------------------------------
# Public properties
# ---------------------------------------------------------------------------


def test_case_name_property() -> None:
    composite = _make_composite(strategies={"alpha": None}, case_name="foo")
    assert composite.case_name == "foo"


def test_strategies_property_returns_copy() -> None:
    alpha = _FakeStrategy(name="alpha")
    composite = _make_composite(strategies={"alpha": alpha, "beta": None})
    snapshot = composite.strategies
    assert snapshot == {"alpha": alpha, "beta": None}
    # Mutating the returned dict must not affect the composite
    snapshot["alpha"] = None
    assert composite.strategies["alpha"] is alpha


# ---------------------------------------------------------------------------
# Default merge requires dataclass proposals
# ---------------------------------------------------------------------------


def test_default_cluster_merge_rejects_non_dataclass() -> None:
    """Default merge requires dataclass proposals (uses replace())."""

    class _NotADataclass:
        def __init__(self) -> None:
            self.confidence = 0.5
            self.strategy = "x"
            self.reasoning = ""
            self.evidence: dict[str, Any] = {}

    a = _NotADataclass()
    b = _NotADataclass()
    with pytest.raises(TypeError, match="dataclass proposals"):
        default_cluster_merge([a, b])  # type: ignore[list-item]


def test_default_cluster_merge_empty_raises() -> None:
    """Default merge asserts at least one proposal in the cluster."""
    with pytest.raises(AssertionError):
        default_cluster_merge([])


def test_default_cluster_merge_single_proposal_returns_verbatim() -> None:
    """Single proposal in the cluster is returned identity-equal."""
    p = _proposal()
    assert default_cluster_merge([p]) is p


# ---------------------------------------------------------------------------
# min_confidence promotion-time floor (polish-bundle 2026-06-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_min_confidence_none_default_no_filtering() -> None:
    """Default ``min_confidence=None`` keeps every proposal (back-compat).

    L3/L7 axes don't wire the knob; this pins the no-filter default so
    their behaviour stays byte-identical.
    """
    strategy = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(pid="hi", confidence=0.95),
            _proposal(pid="lo", confidence=0.1),
        ],
    )
    composite = _make_composite(strategies={"alpha": strategy})
    proposals = await composite.propose()
    assert len(proposals) == 2
    metrics = composite.metrics()
    assert metrics["fake_axis_below_min_confidence_dropped"] == 0


@pytest.mark.asyncio
async def test_min_confidence_drops_below_floor_keeps_above() -> None:
    """``min_confidence`` set → proposals with ``confidence < floor`` are
    dropped post-merge; ``>=`` floor survives."""
    strategy = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(pid="hi", confidence=0.9),
            _proposal(pid="mid", confidence=0.5),
            _proposal(pid="lo", confidence=0.1),
        ],
    )
    composite = _make_composite(
        strategies={"alpha": strategy},
        min_confidence=0.5,
    )
    proposals = await composite.propose()
    surviving = {p.proposal_id for p in proposals}
    assert surviving == {"hi", "mid"}
    metrics = composite.metrics()
    assert metrics["fake_axis_below_min_confidence_dropped"] == 1
    # proposals_emitted counter reflects POST-filter count.
    assert metrics["fake_axis_proposals_emitted"] == 2


@pytest.mark.asyncio
async def test_min_confidence_drops_all_when_all_below() -> None:
    """All proposals below floor → empty list, drop counter == cluster count."""
    strategy = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(pid="lo1", confidence=0.1),
            _proposal(pid="lo2", confidence=0.2),
        ],
    )
    composite = _make_composite(
        strategies={"alpha": strategy},
        min_confidence=0.5,
    )
    proposals = await composite.propose()
    assert proposals == []
    metrics = composite.metrics()
    assert metrics["fake_axis_below_min_confidence_dropped"] == 2
    assert metrics["fake_axis_proposals_emitted"] == 0
    # no_op stays at 0 — the strategy fired and returned proposals; the
    # composite filtered them out post-merge. no_op is reserved for the
    # all-None strategies path.
    assert metrics["fake_axis_no_op"] == 0


@pytest.mark.asyncio
async def test_min_confidence_boundary_inclusive() -> None:
    """``confidence == min_confidence`` is kept (>= not >)."""
    strategy = _FakeStrategy(
        name="alpha",
        results=[
            _proposal(pid="boundary", confidence=0.5),
        ],
    )
    composite = _make_composite(
        strategies={"alpha": strategy},
        min_confidence=0.5,
    )
    proposals = await composite.propose()
    assert len(proposals) == 1
    metrics = composite.metrics()
    assert metrics["fake_axis_below_min_confidence_dropped"] == 0
