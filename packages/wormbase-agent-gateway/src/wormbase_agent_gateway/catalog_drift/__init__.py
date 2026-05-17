"""L2 lake-side catalog-drift detection subpackage.

Public surface for the L2 Compounding axis (the **8th lake-side
axis**; **5th from-day-one consumer** of :class:`LakeLoopComposite`):

  * :class:`ProposedCatalogDrift` — strategy output dataclass; folds
    1:1 onto a ``catalog_drift_proposed`` ledger entry.
  * :class:`CatalogDriftStrategy` — Protocol every strategy
    implements (runtime_checkable).
  * :func:`make_drift_id` — deterministic SHA-256-prefix hash
    re-exported from :mod:`wormbase_ledger` (over
    ``(source_id, table_id, column, drift_kind, before, after)`` —
    merge-across-strategy posture; mirrors L5+L8, diverges from
    L6+L1).
  * **1 NEW lightweight Reader Protocol** (NOT a cross-axis chain —
    it reads catalog-mirror substrate ``external_catalog_imported``
    entries, not a peer L-axis projection; per spec §4.6):

      * :class:`CatalogSnapshotReader` returning
        :class:`CatalogSnapshot` + :class:`CatalogTable` +
        :class:`CatalogColumn` records.
  * :class:`TableSetDriftStrategy` — productive today on
    ``added_table_ids`` / ``removed_table_ids`` per Sub-wave A's
    payload-shape verification.
  * :class:`ColumnSetDriftStrategy` — configured · empty-upstream
    today (``CatalogTable.columns == ()``); productive once richer
    catalog emitters land.
  * :class:`ColumnTypeDriftStrategy` — configured · empty-upstream
    today (same posture); productive once per-column type metadata
    is available.
  * :func:`make_composite_catalog_drift_service` — Optional-Effect
    Injection composition over the 3 strategies via
    :class:`LakeLoopComposite` (doctrine case 16 — **fifth from-day-one
    consumer** of the abstraction, after L5 + L6 + L8 + L1). ~12 LOC
    factory instead of a ~250 LOC custom composite class.

Sub-wave B (2026-06-09) ships these. Sub-wave C wires a concrete
``LedgerCatalogSnapshotReader`` impl + the
``make_catalog_drift_discovery_reactivity`` factory + admin
endpoints; Sub-wave D ships the admin ``/lake/catalog-drift``
dashboard surface.

Cross-axis chain count: stays at **3** (L4→L3, L6→L5, L8→L5). L2's
:class:`CatalogSnapshotReader` is a "platform reader" — distinct
category per spec §4.6 doctrine clarification.
"""
from __future__ import annotations

from .composite import make_composite_catalog_drift_service
from .protocol import (
    AcknowledgedDriftReader,
    AcknowledgedDriftRecord,
    CatalogColumn,
    CatalogDriftStrategy,
    CatalogSnapshot,
    CatalogSnapshotReader,
    CatalogTable,
    ProposedCatalogDrift,
    make_drift_id,
)
from .strategies import (
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    TableSetDriftStrategy,
)

__all__ = [
    "AcknowledgedDriftReader",
    "AcknowledgedDriftRecord",
    "CatalogColumn",
    "CatalogDriftStrategy",
    "CatalogSnapshot",
    "CatalogSnapshotReader",
    "CatalogTable",
    "ColumnSetDriftStrategy",
    "ColumnTypeDriftStrategy",
    "ProposedCatalogDrift",
    "TableSetDriftStrategy",
    "make_composite_catalog_drift_service",
    "make_drift_id",
]
