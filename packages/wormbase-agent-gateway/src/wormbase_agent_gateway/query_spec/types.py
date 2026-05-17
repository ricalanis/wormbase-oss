"""QuerySpec Protocol — structured query intent (per spec §3.5)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TimeGrain = Literal["day", "week", "month", "quarter", "year"]


@dataclass(frozen=True)
class QuerySpec:
    metric: str | None = None
    dimensions: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    filter: dict[str, Any] | None = None
    time_grain: TimeGrain | None = None
    time_range: tuple[str, str] | None = None
    limit: int = 1000

    def validate(self) -> None:
        from .errors import QuerySpecValidationError
        if not self.metric and not (self.dimensions or self.measures):
            raise QuerySpecValidationError("must supply either `metric` or `dimensions+measures`")


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    upstream_kind: str
    upstream_resource_id: str
    parameter_values: tuple[Any, ...] = ()
    masking_policies_applied: tuple[str, ...] = ()
    metric_name: str | None = None


@dataclass(frozen=True)
class UpstreamPlan:
    """Output of `plan()` — what `compile()` consumes."""
    upstream_kind: str                                # "snowflake" | "dbt" | etc.
    upstream_resource_id: str
    primary_table: str                                # qualified upstream table name
    join_graph: tuple[tuple[str, str], ...] = ()      # ((from_table, to_table), ...) edges
    metric_definition: dict | None = None             # full MetricDefinition.model_dump() if mode (a)
