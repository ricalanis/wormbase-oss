"""QuerySpec — structured query intent (spec §3.5).

Agents submit `QuerySpec` instead of raw SQL. The pipeline is:

    validate(spec, catalog) -> plan(spec, catalog) -> compile(spec, plan) -> CompiledQuery

The semantic layer is the contract; raw SQL is the federate-mode escape hatch only.
"""
from .compile import compile_to_sql
from .errors import (
    CompilationError,
    DimensionNotFound,
    MeasureNotFound,
    MetricNotFound,
    QuerySpecError,
    QuerySpecValidationError,
)
from .plan import plan_query
from .types import CompiledQuery, QuerySpec, TimeGrain, UpstreamPlan
from .validate import CatalogClient, validate_query_spec

__all__ = [
    "CatalogClient",
    "CompilationError",
    "CompiledQuery",
    "DimensionNotFound",
    "MeasureNotFound",
    "MetricNotFound",
    "QuerySpec",
    "QuerySpecError",
    "QuerySpecValidationError",
    "TimeGrain",
    "UpstreamPlan",
    "compile_to_sql",
    "plan_query",
    "validate_query_spec",
]
