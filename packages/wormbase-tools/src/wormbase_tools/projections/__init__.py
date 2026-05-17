"""Pure-Python projections for the OSS audit-replay path.

Vendoring seam — what is here vs. what is re-imported
=====================================================

The hosted WormBase plane folds the ledger inside the
``wormbase_ledger.projections`` package using SQLAlchemy + asyncpg / aiosqlite
to materialise rows into ``projection_*`` SQL tables. That code path is
**deliberately not importable from this package**: an auditor must be able to
``pip install wormbase-tools`` and replay a snapshot from a clean venv,
without Postgres, without async I/O, without the dashboard.

What is **vendored** here (re-implemented in pure Python, no SQL):

* :func:`fold_kpis` — folds ``emit_kpi_proposed``, ``emit_kpi_node``, and
  ``emit_source_golded`` execute-rows into a deterministic dict keyed by
  KPI id. This mirrors the in-memory portion of
  ``wormbase_ledger.projections.builder._apply_execute`` for kpi-tree-shaped
  entries plus the ``_fold_kpis`` helper from
  ``wormbase_core.mcp_tools.read_tools``.

* :func:`compute_kpi_value` — picks the canonical numeric value for a KPI
  id from its proposal entry plus any ``source_golded`` entries whose
  ``gold_artifact_id`` is referenced by the KPI's ``source_ids``. This is
  the mapping that ``apps/dashboard``'s ``/api/kpis/[id]`` route encodes
  in TypeScript today; vendored here to keep the auditor path
  Postgres-free.

What is **NOT here** (and would defeat the purpose if it were):

* ``SQLAlchemy`` projection-table writes (``persist_projections``).
* Async DB sessions or engine wiring.
* Anything that imports ``wormbase_ledger`` directly — the seam is a
  vendoring seam, not a soft re-import. If ``wormbase_ledger`` is on the
  auditor's machine, this package neither uses it nor depends on it.

Re-exports (public API)
-----------------------

The two vendored functions plus a small ``ProjectionState`` dataclass are
re-exported below. New ledger entry kinds that contribute to a KPI value
must register their fold here (per ``CLAUDE.md`` invariant 11) so the
auditor's replay stays in lock-step with the hosted plane.
"""

from wormbase_tools.projections.kpis import (
    KpiNode,
    ProjectionState,
    compute_kpi_value,
    fold_kpis,
)

__all__ = [
    "KpiNode",
    "ProjectionState",
    "compute_kpi_value",
    "fold_kpis",
]
