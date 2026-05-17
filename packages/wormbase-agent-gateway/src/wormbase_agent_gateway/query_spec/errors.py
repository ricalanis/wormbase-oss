"""QuerySpec error taxonomy."""
from __future__ import annotations


class QuerySpecError(RuntimeError):
    """Base."""


class QuerySpecValidationError(QuerySpecError):
    """Spec doesn't satisfy basic constraints (e.g. neither metric nor dimensions+measures supplied)."""


class MetricNotFound(QuerySpecError):
    """Spec referenced a metric name not present in the catalog-mirror registry."""


class DimensionNotFound(QuerySpecError):
    pass


class MeasureNotFound(QuerySpecError):
    pass


class CompilationError(QuerySpecError):
    """compile() couldn't emit SQL — e.g. unsupported dialect, ambiguous join graph."""
