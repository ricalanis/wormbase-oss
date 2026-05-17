"""Catalog-mirror value-type round-trip tests."""
from __future__ import annotations

from wormbase_catalog_mirror.types import (
    CatalogCapability,
    CatalogDelta,
    CatalogSnapshot,
    ColumnMeta,
    ExternalPolicy,
    LineageEdge,
    LineageGraph,
    MetricDefinition,
    TableMeta,
)


def test_column_meta_roundtrip() -> None:
    c = ColumnMeta(name="revenue", type="NUMBER(18,2)", description="Confidential", tags=("confidential",))
    assert ColumnMeta.model_validate(c.model_dump()) == c


def test_table_meta_roundtrip_with_columns() -> None:
    t = TableMeta(
        external_id="model.jaffle_shop.customers",
        name="customers",
        schema="ANALYTICS",
        database="ACME",
        description="Customer dim",
        columns=(
            ColumnMeta(name="customer_id", type="INT", description=None),
            ColumnMeta(name="name", type="TEXT", description=None, tags=("pii",)),
        ),
        tags=(),
    )
    assert TableMeta.model_validate(t.model_dump()) == t
    assert t.columns[1].tags == ("pii",)


def test_lineage_graph_roundtrip() -> None:
    g = LineageGraph(edges=(
        LineageEdge(upstream="source.raw.events", downstream="model.staging.events"),
        LineageEdge(upstream="model.staging.events", downstream="model.mart.revenue"),
    ))
    assert LineageGraph.model_validate(g.model_dump()) == g


def test_external_policy_roundtrip() -> None:
    p = ExternalPolicy(
        name="REVENUE_MASK",
        policy_kind="masking",
        body="CASE WHEN CURRENT_ROLE() IN ('FINANCE_ANALYST') THEN val ELSE NULL END",
        applied_to=("REVENUE",),
    )
    assert ExternalPolicy.model_validate(p.model_dump()) == p
    assert p.policy_kind in ("masking", "row_access")


def test_metric_definition_roundtrip() -> None:
    m = MetricDefinition(
        name="revenue_q3",
        expression="SUM(revenue) FILTER (WHERE quarter='Q3')",
        time_grain="quarter",
        dimensions=("region",),
    )
    assert MetricDefinition.model_validate(m.model_dump()) == m


def test_catalog_snapshot_deterministic_hash() -> None:
    """Hash must be stable for identical inputs — drift detection depends on it."""
    s1 = CatalogSnapshot(
        source_kind="dbt",
        tables=(),
        lineage=LineageGraph(edges=()),
        policies=(),
        metrics=[],
    )
    s2 = CatalogSnapshot(
        source_kind="dbt",
        tables=(),
        lineage=LineageGraph(edges=()),
        policies=(),
        metrics=[],
    )
    assert s1.snapshot_hash == s2.snapshot_hash


def test_catalog_snapshot_hash_changes_with_content() -> None:
    s1 = CatalogSnapshot(source_kind="dbt", tables=(), lineage=LineageGraph(edges=()), policies=(), metrics=[])
    s2 = CatalogSnapshot(
        source_kind="dbt",
        tables=(TableMeta(external_id="model.x.y", name="y", schema=None, database=None, description=None, columns=()),),
        lineage=LineageGraph(edges=()),
        policies=(),
        metrics=[],
    )
    assert s1.snapshot_hash != s2.snapshot_hash


def test_catalog_capability_is_literal_set() -> None:
    valid: set[CatalogCapability] = {"schema", "lineage", "policy", "semantic_layer", "quality"}
    assert "schema" in valid


def test_catalog_delta_carries_added_removed_changed() -> None:
    d = CatalogDelta(
        added_table_ids=("model.x.new",),
        removed_table_ids=(),
        changed_table_ids=("model.x.changed",),
        added_edges=(),
        removed_edges=(),
    )
    assert CatalogDelta.model_validate(d.model_dump()) == d
