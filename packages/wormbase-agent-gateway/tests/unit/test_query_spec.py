"""Unit tests for the QuerySpec validate -> plan -> compile pipeline (Wave 2 Task 6).

Covers spec §3.5 — agents submit structured intent (QuerySpec) instead of raw SQL.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.query_spec import (
    CompilationError,
    CompiledQuery,
    DimensionNotFound,
    MeasureNotFound,
    MetricNotFound,
    QuerySpec,
    QuerySpecValidationError,
    UpstreamPlan,
    compile_to_sql,
    plan_query,
    validate_query_spec,
)


# ---------------------------------------------------------------------------
# Mock catalog client
# ---------------------------------------------------------------------------


class FakeCatalogClient:
    """In-memory CatalogClient satisfying the Protocol for unit tests."""

    def __init__(
        self,
        *,
        metrics: dict[str, dict] | None = None,
        tables: list[dict] | None = None,
    ) -> None:
        self._metrics = metrics or {}
        self._tables = tables or []

    async def get_metric(self, name: str) -> dict | None:
        return self._metrics.get(name)

    async def get_table(self, external_id: str) -> dict | None:
        for t in self._tables:
            if t.get("external_id") == external_id or t.get("name") == external_id:
                return t
        return None

    async def list_tables(self) -> list[dict]:
        return list(self._tables)


# ---------------------------------------------------------------------------
# QuerySpec.validate — shape checks
# ---------------------------------------------------------------------------


def test_queryspec_validate_rejects_empty_spec() -> None:
    spec = QuerySpec()
    with pytest.raises(QuerySpecValidationError) as ei:
        spec.validate()
    assert "either `metric` or `dimensions+measures`" in str(ei.value)


def test_queryspec_validate_accepts_metric_only() -> None:
    spec = QuerySpec(metric="q3_net_revenue")
    spec.validate()  # no exception


def test_queryspec_validate_accepts_dimensions_only() -> None:
    spec = QuerySpec(dimensions=("country",))
    spec.validate()  # no exception


def test_queryspec_validate_accepts_measures_only() -> None:
    spec = QuerySpec(measures=("sum(revenue)",))
    spec.validate()


# ---------------------------------------------------------------------------
# validate_query_spec — catalog-driven checks
# ---------------------------------------------------------------------------


async def test_validate_query_spec_metric_mode_happy_path() -> None:
    catalog = FakeCatalogClient(
        metrics={
            "q3_net_revenue": {
                "name": "q3_net_revenue",
                "expression": "SUM(amount)",
                "source_table_id": "tbl.orders",
                "source_kind": "snowflake",
            }
        }
    )
    spec = QuerySpec(metric="q3_net_revenue")
    await validate_query_spec(spec, catalog=catalog)


async def test_validate_query_spec_raises_metric_not_found() -> None:
    catalog = FakeCatalogClient(metrics={})
    spec = QuerySpec(metric="missing_metric")
    with pytest.raises(MetricNotFound) as ei:
        await validate_query_spec(spec, catalog=catalog)
    assert "missing_metric" in str(ei.value)


async def test_validate_query_spec_adhoc_mode_happy_path() -> None:
    catalog = FakeCatalogClient(
        tables=[
            {
                "name": "ORDERS",
                "external_id": "snowflake.ORDERS",
                "upstream_kind": "snowflake",
                "columns": [
                    {"name": "country"},
                    {"name": "revenue"},
                    {"name": "order_date"},
                ],
            }
        ]
    )
    spec = QuerySpec(dimensions=("country",), measures=("sum(revenue)",))
    await validate_query_spec(spec, catalog=catalog)


async def test_validate_query_spec_raises_dimension_not_found() -> None:
    catalog = FakeCatalogClient(
        tables=[
            {
                "name": "ORDERS",
                "columns": [{"name": "country"}, {"name": "revenue"}],
            }
        ]
    )
    spec = QuerySpec(dimensions=("nonexistent_dim",), measures=("sum(revenue)",))
    with pytest.raises(DimensionNotFound) as ei:
        await validate_query_spec(spec, catalog=catalog)
    assert "nonexistent_dim" in str(ei.value)


async def test_validate_query_spec_raises_measure_not_found() -> None:
    catalog = FakeCatalogClient(
        tables=[
            {
                "name": "ORDERS",
                "columns": [{"name": "country"}, {"name": "revenue"}],
            }
        ]
    )
    spec = QuerySpec(dimensions=("country",), measures=("sum(nonexistent_col)",))
    with pytest.raises(MeasureNotFound) as ei:
        await validate_query_spec(spec, catalog=catalog)
    assert "nonexistent_col" in str(ei.value)


async def test_validate_query_spec_bare_column_measure() -> None:
    """Measure without aggregation function still validates the column name."""
    catalog = FakeCatalogClient(
        tables=[{"name": "T", "columns": [{"name": "x"}, {"name": "y"}]}]
    )
    spec = QuerySpec(measures=("x",))
    await validate_query_spec(spec, catalog=catalog)

    spec2 = QuerySpec(measures=("bogus",))
    with pytest.raises(MeasureNotFound):
        await validate_query_spec(spec2, catalog=catalog)


# ---------------------------------------------------------------------------
# plan_query — picks upstream
# ---------------------------------------------------------------------------


async def test_plan_query_metric_mode_returns_single_table_plan() -> None:
    metric_def = {
        "name": "q3_net_revenue",
        "expression": "SUM(amount)",
        "source_table_id": "snowflake.ORDERS",
        "source_kind": "snowflake",
    }
    catalog = FakeCatalogClient(
        metrics={"q3_net_revenue": metric_def},
        tables=[
            {
                "name": "ORDERS",
                "external_id": "snowflake.ORDERS",
                "upstream_kind": "snowflake",
                "columns": [{"name": "amount"}],
            }
        ],
    )
    spec = QuerySpec(metric="q3_net_revenue")
    plan = await plan_query(spec, catalog=catalog)
    assert isinstance(plan, UpstreamPlan)
    assert plan.upstream_kind == "snowflake"
    assert plan.upstream_resource_id == "snowflake.ORDERS"
    assert plan.primary_table == "ORDERS"
    assert plan.metric_definition == metric_def


async def test_plan_query_metric_mode_raises_when_metric_missing() -> None:
    catalog = FakeCatalogClient(metrics={})
    spec = QuerySpec(metric="nope")
    with pytest.raises(MetricNotFound):
        await plan_query(spec, catalog=catalog)


async def test_plan_query_adhoc_mode_picks_matching_table() -> None:
    catalog = FakeCatalogClient(
        tables=[
            {
                "name": "USERS",
                "external_id": "snowflake.USERS",
                "upstream_kind": "snowflake",
                "columns": [{"name": "user_id"}, {"name": "country"}],
            },
            {
                "name": "ORDERS",
                "external_id": "snowflake.ORDERS",
                "upstream_kind": "snowflake",
                "columns": [
                    {"name": "country"},
                    {"name": "revenue"},
                    {"name": "order_date"},
                ],
            },
        ]
    )
    spec = QuerySpec(dimensions=("country",), measures=("sum(revenue)",))
    plan = await plan_query(spec, catalog=catalog)
    assert plan.primary_table == "ORDERS"
    assert plan.upstream_kind == "snowflake"
    assert plan.upstream_resource_id == "snowflake.ORDERS"


async def test_plan_query_adhoc_raises_when_no_single_table_covers() -> None:
    catalog = FakeCatalogClient(
        tables=[
            {"name": "USERS", "columns": [{"name": "user_id"}, {"name": "country"}]},
            {"name": "ORDERS", "columns": [{"name": "revenue"}, {"name": "order_date"}]},
        ]
    )
    # country lives in USERS, revenue in ORDERS — no single table covers both
    spec = QuerySpec(dimensions=("country",), measures=("sum(revenue)",))
    with pytest.raises(CompilationError) as ei:
        await plan_query(spec, catalog=catalog)
    assert "multi-table joins are v1.1" in str(ei.value)


# ---------------------------------------------------------------------------
# compile_to_sql — emits SQL
# ---------------------------------------------------------------------------


def test_compile_to_sql_adhoc_happy_path() -> None:
    spec = QuerySpec(
        dimensions=("country",),
        measures=("sum(revenue)",),
        limit=500,
    )
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
    )
    compiled = compile_to_sql(spec, plan)
    assert isinstance(compiled, CompiledQuery)
    assert compiled.upstream_kind == "snowflake"
    assert compiled.upstream_resource_id == "snowflake.ORDERS"
    assert "SELECT country, sum(revenue) FROM ORDERS" in compiled.sql
    assert "GROUP BY country" in compiled.sql
    assert "LIMIT 500" in compiled.sql
    assert compiled.parameter_values == ()
    assert compiled.metric_name is None


def test_compile_to_sql_default_limit_1000() -> None:
    spec = QuerySpec(dimensions=("country",), measures=("revenue",))
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
    )
    compiled = compile_to_sql(spec, plan)
    assert "LIMIT 1000" in compiled.sql


def test_compile_to_sql_includes_filter_as_parameterized_where() -> None:
    spec = QuerySpec(
        dimensions=("country",),
        measures=("revenue",),
        filter={"region": "EMEA"},
    )
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
    )
    compiled = compile_to_sql(spec, plan)
    assert "WHERE region = %s" in compiled.sql
    assert compiled.parameter_values == ("EMEA",)


def test_compile_to_sql_includes_time_range_clause() -> None:
    spec = QuerySpec(
        dimensions=("country",),
        measures=("revenue",),
        time_range=("2026-01-01", "2026-03-31"),
    )
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
    )
    compiled = compile_to_sql(spec, plan)
    assert "event_time BETWEEN %s AND %s" in compiled.sql
    assert compiled.parameter_values == ("2026-01-01", "2026-03-31")


def test_compile_to_sql_metric_mode_uses_expression() -> None:
    spec = QuerySpec(metric="q3_net_revenue", dimensions=("country",))
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
        metric_definition={
            "name": "q3_net_revenue",
            "expression": "SUM(amount)",
        },
    )
    compiled = compile_to_sql(spec, plan)
    assert "SUM(amount) AS q3_net_revenue" in compiled.sql
    assert "FROM ORDERS" in compiled.sql
    assert "GROUP BY country" in compiled.sql
    assert compiled.metric_name == "q3_net_revenue"


def test_compile_to_sql_records_masking_policy_provenance() -> None:
    spec = QuerySpec(dimensions=("country",), measures=("revenue",))
    plan = UpstreamPlan(
        upstream_kind="snowflake",
        upstream_resource_id="snowflake.ORDERS",
        primary_table="ORDERS",
    )
    compiled = compile_to_sql(
        spec,
        plan,
        masking_policies=("pii_email_mask", "pii_phone_mask"),
    )
    # v1: policies recorded for audit but NOT wrapped in SQL (Snowflake masks at DB level)
    assert compiled.masking_policies_applied == ("pii_email_mask", "pii_phone_mask")


def test_compile_to_sql_rejects_non_snowflake_dialect() -> None:
    spec = QuerySpec(dimensions=("x",), measures=("y",))
    plan = UpstreamPlan(
        upstream_kind="bigquery",
        upstream_resource_id="bq.dataset.t",
        primary_table="dataset.t",
    )
    with pytest.raises(CompilationError) as ei:
        compile_to_sql(spec, plan)
    assert "bigquery" in str(ei.value)
    assert "only snowflake" in str(ei.value)


# ---------------------------------------------------------------------------
# End-to-end pipeline integration
# ---------------------------------------------------------------------------


async def test_full_pipeline_metric_mode_end_to_end() -> None:
    catalog = FakeCatalogClient(
        metrics={
            "q3_net_revenue": {
                "name": "q3_net_revenue",
                "expression": "SUM(amount)",
                "source_table_id": "snowflake.ORDERS",
                "source_kind": "snowflake",
            }
        },
        tables=[
            {
                "name": "ORDERS",
                "external_id": "snowflake.ORDERS",
                "upstream_kind": "snowflake",
                "columns": [{"name": "amount"}, {"name": "country"}],
            }
        ],
    )
    spec = QuerySpec(metric="q3_net_revenue", dimensions=("country",))
    await validate_query_spec(spec, catalog=catalog)
    plan = await plan_query(spec, catalog=catalog)
    compiled = compile_to_sql(spec, plan, masking_policies=("pii_mask",))
    assert compiled.metric_name == "q3_net_revenue"
    assert "SUM(amount) AS q3_net_revenue" in compiled.sql
    assert "FROM ORDERS" in compiled.sql
    assert "GROUP BY country" in compiled.sql
    assert compiled.masking_policies_applied == ("pii_mask",)
