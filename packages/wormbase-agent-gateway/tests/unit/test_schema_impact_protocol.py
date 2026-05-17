"""L4 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_impact_id` determinism / replay stability.
  * Per-tuple distinguishability (every component of the canonical
    tuple affects the hash).
  * Each strategy + the composite implements the
    :class:`SchemaImpactService` Protocol (runtime_checkable).
  * :class:`LineageEdgeReader` Protocol is runtime_checkable + a fake
    impl satisfies it (cross-axis read pattern conformance).
  * Dataclass shape + frozenness.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_agent_gateway.schema_impact import (
    ColumnChange,
    CompositeSchemaImpactService,
    DbtTestImpactStrategy,
    LineageEdgeImpactStrategy,
    LineageEdgeReader,
    LineageEdgeRecord,
    ProposedImpact,
    SchemaImpactService,
    TypeCoercionImpactStrategy,
    make_impact_id,
)


def test_make_impact_id_is_deterministic() -> None:
    """Same inputs → same impact_id across calls (replay-stable)."""
    a = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    b = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_impact_id_distinguishes_change_kind() -> None:
    """Same tuple but different change_kind → different impact_id."""
    drop = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    typ = make_impact_id(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_type_changed",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    assert drop != typ


def test_make_impact_id_distinguishes_every_tuple_component() -> None:
    """Each of the 6 inputs participates in the hash distinctly."""
    base = dict(
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
    )
    base_id = make_impact_id(**base)
    for key, mutated in [
        ("source_id", "src-OTHER"),
        ("src_table", "src-001.public.other"),
        ("src_column", "other_id"),
        ("change_kind", "column_added"),
        ("tgt_table_id", "dbt.marts.other"),
        ("tgt_column", "other_id"),
    ]:
        kwargs = dict(base)
        kwargs[key] = mutated
        assert make_impact_id(**kwargs) != base_id, (
            f"impact_id collided when mutating {key}"
        )


def test_strategies_satisfy_schema_impact_service_protocol() -> None:
    """All 3 strategies + the composite are instances of
    :class:`SchemaImpactService` per ``runtime_checkable``."""

    class _FakeReader:
        async def list_confirmed_edges_for_source_column(
            self, *, source_id, src_column, company_id,
        ):
            return []

    class _FakeDbtTestReader:
        async def get_tests_for_model(self, model_id):
            return []

    le = LineageEdgeImpactStrategy(lineage_edge_reader=_FakeReader())
    dt = DbtTestImpactStrategy(test_reader=_FakeDbtTestReader())
    tc = TypeCoercionImpactStrategy()
    composite = CompositeSchemaImpactService()

    for service in (le, dt, tc, composite):
        assert isinstance(service, SchemaImpactService), (
            f"{type(service).__name__} does not satisfy SchemaImpactService"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_lineage_edge_reader_protocol_runtime_checkable() -> None:
    """:class:`LineageEdgeReader` is runtime_checkable; a fake impl matches.

    Pin: the cross-axis read Protocol is a runtime-checkable Protocol so
    callers can structurally verify reader conformance at boot time.
    """

    class _ProperReader:
        async def list_confirmed_edges_for_source_column(
            self, *, source_id: str, src_column: str, company_id: UUID,
        ) -> list[LineageEdgeRecord]:
            return []

    reader = _ProperReader()
    assert isinstance(reader, LineageEdgeReader)

    class _MissingMethod:
        async def some_other_method(self):
            return []

    bad = _MissingMethod()
    assert not isinstance(bad, LineageEdgeReader)


@pytest.mark.asyncio
async def test_lineage_edge_reader_returns_records() -> None:
    """A LineageEdgeReader returns ``LineageEdgeRecord`` instances."""

    sample = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )

    class _Reader:
        async def list_confirmed_edges_for_source_column(
            self, *, source_id, src_column, company_id,
        ):
            return [sample]

    r = _Reader()
    out = await r.list_confirmed_edges_for_source_column(
        source_id="src-001",
        src_column="customer_id",
        company_id=uuid4(),
    )
    assert out == [sample]
    assert isinstance(out[0], LineageEdgeRecord)


def test_lineage_edge_record_exposes_minimum_coupling_fields() -> None:
    """:class:`LineageEdgeRecord` is the consumer-owned subset of L3's edge.

    Pins the documented minimum-coupling field set so future L3 payload
    additions don't accidentally leak into the cross-axis Protocol.
    """
    rec = LineageEdgeRecord(
        edge_id="e",
        src_table_id="a",
        src_column="b",
        tgt_table_id="c",
        tgt_column="d",
        confidence=0.5,
        strategy="dbt_manifest",
    )
    # The dataclass exposes exactly these seven fields.
    expected_fields = {
        "edge_id",
        "src_table_id",
        "src_column",
        "tgt_table_id",
        "tgt_column",
        "confidence",
        "strategy",
    }
    actual = {f for f in rec.__dataclass_fields__}
    assert actual == expected_fields, (
        f"LineageEdgeRecord field surface drift: extra={actual - expected_fields}, "
        f"missing={expected_fields - actual}"
    )


def test_proposed_impact_is_frozen() -> None:
    """:class:`ProposedImpact` is a frozen dataclass."""
    impact = ProposedImpact(
        impact_id="abc",
        source_id="src-001",
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_dropped",
        impact_kind="tgt_column_orphaned",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        upstream_lineage_edge_id="e1",
        confidence=0.85,
        strategy="lineage_edge",
        reasoning="test",
        evidence={},
    )
    try:
        impact.impact_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedImpact should be frozen")


def test_column_change_is_frozen() -> None:
    """:class:`ColumnChange` is a frozen dataclass."""
    change = ColumnChange(
        src_table="src-001.public.orders",
        src_column="customer_id",
        change_kind="column_type_changed",
        old_type="int",
        new_type="varchar",
    )
    try:
        change.old_type = "other"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ColumnChange should be frozen")


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert LineageEdgeImpactStrategy.name == "lineage_edge"
    assert DbtTestImpactStrategy.name == "dbt_test"
    assert TypeCoercionImpactStrategy.name == "type_coercion"
    assert CompositeSchemaImpactService.name == "composite"
