"""L4 Sub-wave B — per-strategy tests.

Covers each of the 3 strategies independently:

  * :class:`LineageEdgeImpactStrategy` — cross-axis-read fakes, change-
    kind → impact-kind mapping, confidence scaling, edge-strategy
    filtering, confidence floor.
  * :class:`DbtTestImpactStrategy` — dbt-test stub + change-kind
    factors, column-pin filtering, no-add semantics.
  * :class:`TypeCoercionImpactStrategy` — type-family normalisation,
    transition confidence table, no-reader degradation.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_agent_gateway.schema_impact import (
    ColumnChange,
    DbtTestImpactStrategy,
    LineageEdgeImpactStrategy,
    LineageEdgeRecord,
    TypeCoercionImpactStrategy,
    make_impact_id,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeReader:
    """Test double for :class:`LineageEdgeReader`."""

    def __init__(self, edges: list[LineageEdgeRecord] | None = None) -> None:
        self.edges = edges or []
        self.calls: list[tuple[str, str]] = []

    async def list_confirmed_edges_for_source_column(
        self, *, source_id: str, src_column: str, company_id,
    ) -> list[LineageEdgeRecord]:
        self.calls.append((source_id, src_column))
        return [
            e for e in self.edges
            if e.src_column == src_column
        ]


class _FakeDbtTestReader:
    """Test double for L7's :class:`DbtTestReader`."""

    def __init__(self, tests: dict[str, list[dict]] | None = None) -> None:
        self.tests = tests or {}

    async def get_tests_for_model(self, model_id: str):
        return self.tests.get(model_id, [])


# ---------------------------------------------------------------------------
# LineageEdgeImpactStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lineage_edge_strategy_no_edges_returns_empty() -> None:
    """Reader returns [] → strategy emits []."""
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader())
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_lineage_edge_strategy_column_dropped_maps_to_orphaned() -> None:
    """column_dropped + dbt_manifest edge → tgt_column_orphaned at 0.9 × edge.conf."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader([edge]))
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "tgt_column_orphaned"
    assert p.strategy == "lineage_edge"
    assert p.upstream_lineage_edge_id == "e1"
    # 0.99 * 0.90 = 0.891 → rounded to 0.891
    assert p.confidence == pytest.approx(0.891, abs=1e-4)
    assert p.tgt_table_id == "dbt.marts.revenue"
    assert p.tgt_column == "customer_id"


@pytest.mark.asyncio
async def test_lineage_edge_strategy_column_type_changed_maps_to_mismatch() -> None:
    """column_type_changed + edge → tgt_column_type_mismatch at 0.85 × edge.conf."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader([edge]))
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="numeric",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "tgt_column_type_mismatch"
    # 0.99 * 0.85 = 0.8415
    assert p.confidence == pytest.approx(0.8415, abs=1e-4)


@pytest.mark.asyncio
async def test_lineage_edge_strategy_column_added_maps_to_unaware() -> None:
    """column_added → tgt_column_unaware at 0.50 × edge.conf (lower confidence)."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="new_field",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="new_field",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader([edge]))
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="new_field",
            change_kind="column_added",
            old_type=None,
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "tgt_column_unaware"
    # 0.99 * 0.50 = 0.495
    assert p.confidence == pytest.approx(0.495, abs=1e-4)


@pytest.mark.asyncio
async def test_lineage_edge_strategy_naming_edge_gated_by_default() -> None:
    """naming_heuristic edges are filtered out by default."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.85,
        strategy="naming_heuristic",
    )
    strat = LineageEdgeImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
        include_naming_lineage=False,  # default
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_lineage_edge_strategy_naming_edge_opt_in() -> None:
    """include_naming_lineage=True admits non-dbt edges."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.85,
        strategy="naming_heuristic",
    )
    strat = LineageEdgeImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
        include_naming_lineage=True,
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_lineage_edge_strategy_min_confidence_floor() -> None:
    """Edges below min_edge_confidence are skipped even when their
    strategy is included."""
    low = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.60,  # below default 0.85 floor
        strategy="naming_heuristic",
    )
    strat = LineageEdgeImpactStrategy(
        lineage_edge_reader=_FakeReader([low]),
        include_naming_lineage=True,  # admit strategy
        min_edge_confidence=0.85,
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_lineage_edge_strategy_one_impact_per_edge() -> None:
    """Two distinct edges for the same source column → two impacts."""
    e1 = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    e2 = LineageEdgeRecord(
        edge_id="e2",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.churn",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader([e1, e2]))
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 2
    tgts = {p.tgt_table_id for p in proposals}
    assert tgts == {"dbt.marts.revenue", "dbt.marts.churn"}


@pytest.mark.asyncio
async def test_lineage_edge_strategy_impact_id_deterministic() -> None:
    """Impact ID matches :func:`make_impact_id` over the canonical tuple."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader([edge]))
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    expected = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    assert proposals[0].impact_id == expected


@pytest.mark.asyncio
async def test_lineage_edge_strategy_cross_axis_reader_called_with_scope() -> None:
    """Reader is invoked with the correct (source_id, src_column, company_id)."""
    reader = _FakeReader()
    strat = LineageEdgeImpactStrategy(lineage_edge_reader=reader)
    cid = uuid4()
    await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=cid,
    )
    assert reader.calls == [("src-001", "customer_id")]


# ---------------------------------------------------------------------------
# DbtTestImpactStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dbt_test_strategy_not_null_drop_emits_high_confidence() -> None:
    """not_null + column_dropped → dbt_test_breakage at high confidence."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "dbt_test_breakage"
    assert p.strategy == "dbt_test"
    assert p.confidence == pytest.approx(0.95, abs=1e-4)
    # tgt is the source itself
    assert p.tgt_table_id == "dbt.staging.orders"
    assert p.tgt_column == "customer_id"


@pytest.mark.asyncio
async def test_dbt_test_strategy_unique_drop_emits() -> None:
    """unique + column_dropped → dbt_test_breakage."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "unique", "column": "id"},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].impact_kind == "dbt_test_breakage"


@pytest.mark.asyncio
async def test_dbt_test_strategy_accepted_values_type_changed() -> None:
    """accepted_values + column_type_changed → dbt_test_breakage at medium conf."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "accepted_values", "column": "status",
                 "config": {"values": ["a", "b"]}},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="status",
            change_kind="column_type_changed",
            old_type="varchar",
            new_type="int",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    # accepted_values base 0.85 × type_changed factor 0.85 ≈ 0.7225
    assert p.confidence == pytest.approx(0.7225, abs=1e-4)


@pytest.mark.asyncio
async def test_dbt_test_strategy_no_emit_on_column_added() -> None:
    """column_added has zero factor → no emissions."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="customer_id",
            change_kind="column_added",
            old_type=None,
            new_type="int",
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_dbt_test_strategy_filters_test_to_changed_column() -> None:
    """Test on a DIFFERENT column → skipped."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "other_id"},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_dbt_test_strategy_unknown_test_name_skipped() -> None:
    """Tests with unknown names are silently skipped."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "completely_made_up_test", "column": "customer_id"},
            ],
        },
    )
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_dbt_test_strategy_empty_upstream_returns_empty() -> None:
    """Configured-but-empty upstream → no proposals (the empty-upstream
    posture L4 inherits from L7)."""
    reader = _FakeDbtTestReader(tests={})
    strat = DbtTestImpactStrategy(test_reader=reader)
    proposals = await strat.propose_impacts(
        source_id="dbt-prod",
        src_table="dbt.staging.orders",
        change=ColumnChange(
            src_table="dbt.staging.orders",
            src_column="customer_id",
            change_kind="column_dropped",
            old_type="int",
            new_type=None,
        ),
        company_id=uuid4(),
    )
    assert proposals == []


# ---------------------------------------------------------------------------
# TypeCoercionImpactStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_type_coercion_no_reader_returns_empty() -> None:
    """Strategy gracefully no-ops without an injected reader."""
    strat = TypeCoercionImpactStrategy()  # lineage_edge_reader=None
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_type_coercion_only_fires_on_type_changed() -> None:
    """Strategy is no-op for column_added / column_dropped."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    for kind in ("column_added", "column_dropped"):
        proposals = await strat.propose_impacts(
            source_id="src-001",
            src_table="src-001.public.orders",
            change=ColumnChange(
                src_table="src-001.public.orders",
                src_column="amount",
                change_kind=kind,  # type: ignore[arg-type]
                old_type=None if kind == "column_added" else "int",
                new_type="varchar" if kind == "column_added" else None,
            ),
            company_id=uuid4(),
        )
        assert proposals == []


@pytest.mark.asyncio
async def test_type_coercion_int_to_varchar_widening() -> None:
    """int → varchar (widening) → type_coercion_required at 0.85."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "type_coercion_required"
    assert p.strategy == "type_coercion"
    assert p.confidence == pytest.approx(0.85, abs=1e-4)
    assert "CAST int AS varchar" in p.reasoning


@pytest.mark.asyncio
async def test_type_coercion_varchar_to_int_narrowing() -> None:
    """varchar → int (narrowing) → 0.70 (default)."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="status",
        tgt_table_id="dbt.marts.churn",
        tgt_column="status",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="status",
            change_kind="column_type_changed",
            old_type="varchar",
            new_type="int",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].confidence == pytest.approx(0.70, abs=1e-4)


@pytest.mark.asyncio
async def test_type_coercion_type_family_normalisation() -> None:
    """``int4`` and ``integer`` normalise to ``int`` family — same confidence."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    # int4 → varchar widening lookup
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int4",
            new_type="varchar(64)",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].confidence == pytest.approx(0.85, abs=1e-4)


@pytest.mark.asyncio
async def test_type_coercion_unknown_transition_defaults_to_baseline() -> None:
    """Unmapped type transitions → 0.70 default."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="data",
        tgt_table_id="dbt.marts.audit",
        tgt_column="data",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="data",
            change_kind="column_type_changed",
            old_type="json",
            new_type="bytea",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].confidence == pytest.approx(0.70, abs=1e-4)


@pytest.mark.asyncio
async def test_type_coercion_carries_evidence_with_suggestion() -> None:
    """Evidence dict carries the suggested coercion."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([edge]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    ev = proposals[0].evidence
    assert ev["old_type"] == "int"
    assert ev["new_type"] == "varchar"
    assert ev["old_family"] == "int"
    assert ev["new_family"] == "varchar"
    assert ev["suggested_coercion"] == "CAST int AS varchar"
    assert ev["upstream_edge_id"] == "e1"


@pytest.mark.asyncio
async def test_type_coercion_emits_per_downstream_edge() -> None:
    """Multiple downstream edges → one impact per edge."""
    e1 = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    e2 = LineageEdgeRecord(
        edge_id="e2",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.audit",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([e1, e2]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 2
    assert {p.tgt_table_id for p in proposals} == {
        "dbt.marts.revenue",
        "dbt.marts.audit",
    }


@pytest.mark.asyncio
async def test_type_coercion_reader_with_no_edges_returns_empty() -> None:
    """Reader returns no edges → strategy emits nothing."""
    strat = TypeCoercionImpactStrategy(
        lineage_edge_reader=_FakeReader([]),
    )
    proposals = await strat.propose_impacts(
        source_id="src-001",
        src_table="src-001.public.orders",
        change=ColumnChange(
            src_table="src-001.public.orders",
            src_column="amount",
            change_kind="column_type_changed",
            old_type="int",
            new_type="varchar",
        ),
        company_id=uuid4(),
    )
    assert proposals == []
