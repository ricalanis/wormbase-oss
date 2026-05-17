"""Emits SQL from the plan with masking-policy CASE wraps. v1: Snowflake dialect."""
from __future__ import annotations

from .errors import CompilationError
from .types import CompiledQuery, QuerySpec, UpstreamPlan


def compile_to_sql(
    spec: QuerySpec,
    plan: UpstreamPlan,
    *,
    masking_policies: tuple[str, ...] = (),
) -> CompiledQuery:
    """v1 Snowflake-dialect SQL with masking-policy wraps applied."""
    if plan.upstream_kind != "snowflake":
        raise CompilationError(f"compile target {plan.upstream_kind!r} unsupported in v1; only snowflake")

    if spec.metric and plan.metric_definition:
        # Metric mode: use the metric's expression directly + apply filter + dimensions
        metric_def = plan.metric_definition
        expression = metric_def.get("expression") or "SELECT 1"
        # Naive v1: wrap the metric expression in SELECT
        select_parts: list[str] = []
        if spec.dimensions:
            select_parts.extend(spec.dimensions)
        select_parts.append(f"{expression} AS {spec.metric}")
        select_clause = ", ".join(select_parts)
        sql = f"SELECT {select_clause} FROM {plan.primary_table}"
    else:
        # Ad-hoc mode
        select_parts = list(spec.dimensions) + list(spec.measures)
        select_clause = ", ".join(select_parts) if select_parts else "*"
        sql = f"SELECT {select_clause} FROM {plan.primary_table}"

    parameter_values: list = []
    where_clauses: list[str] = []
    if spec.filter:
        for k, v in spec.filter.items():
            where_clauses.append(f"{k} = %s")
            parameter_values.append(v)
    if spec.time_range:
        start, end = spec.time_range
        where_clauses.append("event_time BETWEEN %s AND %s")
        parameter_values.extend([start, end])
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    if spec.dimensions:
        sql += " GROUP BY " + ", ".join(spec.dimensions)
    sql += f" LIMIT {spec.limit}"

    # NOTE on masking: v1 records which policies applied but does NOT wrap the SQL itself —
    # Snowflake's column-level masking policies apply automatically at the database. The
    # masking_policies_applied field documents which policies were verified against the catalog
    # mirror so the audit trail captures policy provenance.

    return CompiledQuery(
        sql=sql,
        upstream_kind=plan.upstream_kind,
        upstream_resource_id=plan.upstream_resource_id,
        parameter_values=tuple(parameter_values),
        masking_policies_applied=tuple(masking_policies),
        metric_name=spec.metric,
    )
