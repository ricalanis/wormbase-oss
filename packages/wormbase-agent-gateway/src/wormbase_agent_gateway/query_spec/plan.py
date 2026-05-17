"""Picks upstream + walks lineage to build an UpstreamPlan."""
from __future__ import annotations

from .types import QuerySpec, UpstreamPlan
from .validate import CatalogClient


async def plan_query(spec: QuerySpec, *, catalog: CatalogClient) -> UpstreamPlan:
    """Returns the upstream plan. v1 ships single-table plans only when metric_definition
    points at a single table; multi-source joins are v1.1."""
    if spec.metric:
        metric = await catalog.get_metric(spec.metric)
        if metric is None:
            from .errors import MetricNotFound
            raise MetricNotFound(f"metric {spec.metric!r}")
        # metric points at a single source-id in v1
        source_table_id = metric.get("source_table_id") or metric.get("source_id")
        table = await catalog.get_table(source_table_id) if source_table_id else None
        primary = table["name"] if table else metric.get("primary_table", "unknown")
        return UpstreamPlan(
            upstream_kind=metric.get("source_kind", "snowflake"),
            upstream_resource_id=source_table_id or "unknown",
            primary_table=primary,
            metric_definition=metric,
        )
    # Ad-hoc mode — pick the first table that contains all dimensions + measures
    all_tables = await catalog.list_tables()
    for t in all_tables:
        col_names = {c["name"] for c in t.get("columns", [])}
        measure_cols = {m.split("(", 1)[1].rstrip(")") if "(" in m else m for m in spec.measures}
        if set(spec.dimensions).issubset(col_names) and measure_cols.issubset(col_names):
            return UpstreamPlan(
                upstream_kind=t.get("upstream_kind", "snowflake"),
                upstream_resource_id=t.get("external_id", t["name"]),
                primary_table=t["name"],
            )
    from .errors import CompilationError
    raise CompilationError(
        "could not find a single table covering all requested dimensions+measures; multi-table joins are v1.1"
    )
