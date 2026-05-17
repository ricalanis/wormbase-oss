"""Validates QuerySpec against catalog-mirror's metric + table registries."""
from __future__ import annotations

from typing import Protocol

from .errors import DimensionNotFound, MeasureNotFound, MetricNotFound
from .types import QuerySpec


class CatalogClient(Protocol):
    async def get_metric(self, name: str) -> dict | None: ...
    async def get_table(self, external_id: str) -> dict | None: ...
    async def list_tables(self) -> list[dict]: ...


async def validate_query_spec(spec: QuerySpec, *, catalog: CatalogClient) -> None:
    spec.validate()  # basic shape check
    if spec.metric:
        metric_def = await catalog.get_metric(spec.metric)
        if metric_def is None:
            raise MetricNotFound(f"metric {spec.metric!r} not in catalog-mirror registry")
    else:
        # Ad-hoc mode — validate dimensions + measures against table columns
        all_tables = await catalog.list_tables()
        all_column_names = {c["name"] for t in all_tables for c in t.get("columns", [])}
        for d in spec.dimensions:
            if d not in all_column_names:
                raise DimensionNotFound(f"dimension {d!r} not found in any catalog table")
        for m in spec.measures:
            # measures can be aggregations like "sum(revenue)" — split on '(' and validate the inner column
            inner = m.split("(", 1)[1].rstrip(")") if "(" in m else m
            if inner not in all_column_names:
                raise MeasureNotFound(f"measure column {inner!r} not found in any catalog table")
