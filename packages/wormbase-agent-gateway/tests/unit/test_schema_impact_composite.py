"""L4 Sub-wave B — composite tests.

Pins:

  * None-ability per strategy (Optional-Effect Injection case 11).
  * Merge dedup: same impact_id from 2 strategies → 1 merged proposal
    with max confidence + composite reasoning.
  * Telemetry counters increment per strategy + on no-op invocations.
  * Upstream lineage edge id threaded through the merged proposal.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_agent_gateway.schema_impact import (
    ColumnChange,
    CompositeSchemaImpactService,
    DbtTestImpactStrategy,
    LineageEdgeImpactStrategy,
    LineageEdgeRecord,
    TypeCoercionImpactStrategy,
    make_impact_id,
)


class _FakeReader:
    def __init__(self, edges: list[LineageEdgeRecord] | None = None) -> None:
        self.edges = edges or []

    async def list_confirmed_edges_for_source_column(
        self, *, source_id, src_column, company_id,
    ) -> list[LineageEdgeRecord]:
        return [e for e in self.edges if e.src_column == src_column]


class _FakeDbtTestReader:
    def __init__(self, tests=None) -> None:
        self.tests = tests or {}

    async def get_tests_for_model(self, model_id):
        return self.tests.get(model_id, [])


def _change(
    kind="column_type_changed",
    old="int",
    new="varchar",
    column="amount",
    table="src-001.public.orders",
) -> ColumnChange:
    return ColumnChange(
        src_table=table,
        src_column=column,
        change_kind=kind,
        old_type=old,
        new_type=new,
    )


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = CompositeSchemaImpactService()
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(kind="column_dropped", new=None),
        company_id=uuid4(),
    )
    assert proposals == []
    metrics = composite.metrics()
    assert metrics["schema_impact_invocations"] == 1
    assert metrics["schema_impact_no_op"] == 1
    assert metrics["schema_impact_impacts_proposed"] == 0
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 0
    assert metrics["schema_impact_strategy_invocations.dbt_test"] == 0
    assert metrics["schema_impact_strategy_invocations.type_coercion"] == 0


@pytest.mark.asyncio
async def test_composite_only_lineage_edge_runs() -> None:
    """``lineage_edge`` set, others None → only that counter increments."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(kind="column_dropped", column="customer_id", new=None),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 1
    assert metrics["schema_impact_strategy_invocations.dbt_test"] == 0
    assert metrics["schema_impact_strategy_invocations.type_coercion"] == 0
    assert metrics["schema_impact_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_only_dbt_test_runs() -> None:
    """``dbt_test`` set, others None → only that counter increments."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    composite = CompositeSchemaImpactService(
        dbt_test=DbtTestImpactStrategy(test_reader=reader),
    )
    proposals = await composite.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=_change(kind="column_dropped", column="customer_id", new=None),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.dbt_test"] == 1
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 0


@pytest.mark.asyncio
async def test_composite_only_type_coercion_runs() -> None:
    """``type_coercion`` set, others None → only that counter increments."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.type_coercion"] == 1
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 0


# ---------------------------------------------------------------------------
# Merge + dedup contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_merge_dedup_when_two_strategies_propose_same_impact() -> None:
    """LineageEdge + TypeCoercion both propose against the same downstream tuple
    for a column_type_changed event — BUT they emit different impact_kinds, so
    the impact_ids differ in change/impact-kind composition.

    Verify that distinct impact_ids stay separate (cluster contract).
    """
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(),  # column_type_changed, int → varchar
        company_id=uuid4(),
    )
    # impact_id includes (change_kind, tgt) but NOT impact_kind; in this
    # case the canonical tuple matches across both strategies' outputs
    # because impact_kind is not in the hash. So they SHOULD merge.
    # Validate: same impact_id ⇒ exactly one merged proposal.
    assert len(proposals) == 1
    p = proposals[0]
    assert p.strategy == "composite"
    # Composite reasoning concatenates both strategies' explanations.
    assert "L3 lineage edge" in p.reasoning
    assert "CAST int AS varchar" in p.reasoning
    # Both per-strategy evidences preserved
    assert "lineage_edge" in p.evidence
    assert "type_coercion" in p.evidence
    # Upstream lineage edge id threaded through
    assert p.upstream_lineage_edge_id == "e1"


@pytest.mark.asyncio
async def test_composite_merge_max_confidence_wins() -> None:
    """When two strategies propose the same impact_id, max confidence wins."""
    # Same impact_id (same canonical tuple), 2 strategies contributing.
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,  # high
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
        # type_coercion sits at 0.70 default for int → bool transitions
        # not in the table; we'll use int → varchar which lookup yields 0.85.
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    # lineage_edge: 0.99 * 0.85 = 0.8415 ; type_coercion: 0.85
    # Max wins → 0.85
    assert p.confidence == pytest.approx(0.85, abs=1e-4)


@pytest.mark.asyncio
async def test_composite_single_strategy_keeps_native_label() -> None:
    """Only one strategy contributes → strategy label stays unwrapped."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(kind="column_dropped", column="customer_id", new=None),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].strategy == "lineage_edge"


@pytest.mark.asyncio
async def test_composite_impact_id_matches_make_impact_id() -> None:
    """Composite output's impact_id matches :func:`make_impact_id`."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(),
        company_id=uuid4(),
    )
    expected = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="amount",
        change_kind="column_type_changed",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
    )
    assert proposals[0].impact_id == expected


@pytest.mark.asyncio
async def test_composite_telemetry_accumulates_across_invocations() -> None:
    """Per-strategy counters accumulate across calls."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )
    cid = uuid4()
    for _ in range(3):
        await composite.propose_impacts(
            source_id="src-001",
            src_table="src-001.public.orders",
            change=_change(kind="column_dropped", column="customer_id", new=None),
            company_id=cid,
        )
    metrics = composite.metrics()
    assert metrics["schema_impact_invocations"] == 3
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 3
    assert metrics["schema_impact_impacts_proposed"] == 3


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_counter_not_incremented() -> None:
    """Strategies wired but each returns [] (e.g. no edges) → empty
    proposals, but ``no_op`` counter does NOT fire (no_op is reserved for
    the "all strategies None" path per the doctrine)."""
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([]),  # no edges
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=_change(kind="column_dropped", new=None),
        company_id=uuid4(),
    )
    assert proposals == []
    metrics = composite.metrics()
    # Strategy ran (counter = 1) but produced nothing — not a no-op.
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 1
    assert metrics["schema_impact_no_op"] == 0
    assert metrics["schema_impact_impacts_proposed"] == 0
