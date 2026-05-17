"""L7 lake-side quality-check discovery subpackage.

Public surface for the L7 Compounding axis:

  * :class:`QualityCheckProposalService` — Protocol every strategy +
    the composite implements.
  * :class:`ProposedQualityCheck` — strategy output dataclass; folds
    1:1 onto a ``quality_check_proposed`` ledger entry.
  * :data:`QualityCheckKind` — strict 7-value Literal covering the L7
    check taxonomy.
  * :class:`CatalogTable` — strategy input dataclass (re-exported from
    :mod:`wormbase_agent_gateway.lineage.protocol` — the two L-axis
    Compounding services share the same per-table input shape).
  * :func:`make_check_id` — deterministic SHA-256 hash for check
    identity.
  * :class:`SchemaPatternStrategy` — metadata-only column-naming +
    type-pattern inference.
  * :class:`DbtTestsStrategy` — manifest dbt-test lift; requires an
    injected :class:`DbtTestReader`.
  * :class:`HistoricalStatsStrategy` — historical-snapshot stable-
    statistics inference; requires an injected
    :class:`HistoricalStatsReader`. Stubbed today (catalog mirror
    doesn't yet emit column-level stats).
  * :class:`CompositeQualityProposalService` — Optional-Effect
    Injection composition over the 3 strategies (doctrine case 10).

Sub-wave B (2026-05-30) ships these. Sub-wave C wires them through
the boot path; Sub-wave D ships the admin ``/lake/quality`` dashboard
surface.
"""
from __future__ import annotations

from .composite import CompositeQualityProposalService
from .protocol import (
    CatalogTable,
    ProposedQualityCheck,
    QualityCheckKind,
    QualityCheckProposalService,
    make_check_id,
)
from .strategies import (
    DbtTestReader,
    DbtTestsStrategy,
    HistoricalStatsReader,
    HistoricalStatsStrategy,
    SchemaPatternStrategy,
    SemanticTypeQualityCheckStrategy,
)

__all__ = [
    "CatalogTable",
    "CompositeQualityProposalService",
    "DbtTestReader",
    "DbtTestsStrategy",
    "HistoricalStatsReader",
    "HistoricalStatsStrategy",
    "ProposedQualityCheck",
    "QualityCheckKind",
    "QualityCheckProposalService",
    "SchemaPatternStrategy",
    "SemanticTypeQualityCheckStrategy",
    "make_check_id",
]
