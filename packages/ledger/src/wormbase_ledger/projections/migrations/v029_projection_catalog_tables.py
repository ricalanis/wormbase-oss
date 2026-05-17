"""v029 — create ``projection_catalog_tables``.

Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on). Per-table
column-metadata mirror folded from the ``catalog_table_imported``
ledger kind. Each ``external_catalog_imported`` snapshot is now
accompanied by one ``catalog_table_imported`` per discovered table,
carrying the per-column structure that L2 TableSet and L8
SchemaShape strategies need to compute real diffs.

Wave 2 motivation: today's ``ExternalCatalogImportedPayload`` carries
only ``table_count`` / ``edge_count`` / ``metric_count`` aggregates —
the per-table column structure is invisible to the ledger and
therefore invisible to the L-axis strategies. With this substrate:

* L2 TableSet — ``CatalogSnapshotReader._make_catalog_table`` (added
  in Sub-wave B) folds the new kind so the strategy actually sees
  every table in the snapshot, not just the count.
* L8 SchemaShape — ``parent_table_columns_lookup`` (closed in Sub-
  wave B) returns real column lists, not the empty tuple that
  ``LedgerCatalogReader._make_catalog_table`` currently emits.

Both consumers were unblocked by close-outs in:

* ``docs/superpowers/notes/2026-06-09-l2-shipped.md`` §Concerns #1, #2
* ``docs/superpowers/notes/2026-06-07-l8-shipped.md`` §Concerns #1

Additive per schema-evolution doctrine Rule 2; net +1 →
KIND_REGISTRY=133, 17 headroom under the 150-kind ceiling per Wave F
Addendum 4. L-axis family count unchanged at 24 of 30 —
``catalog_table_imported`` is substrate, not a lake-axis kind.

Schema invariants:

* Composite PK ``(company_id, source_id, table_id, snapshot_hash)``
  — same logical ``(source_id, table_id)`` across multiple snapshots
  is multiple rows because each snapshot is a point-in-time. L2
  TableSet diffs current vs baseline snapshots, so both snapshots'
  table sets must coexist.
* ``columns`` is JSON-typed — stores a list of
  ``{"name": str, "type": str | None}`` dicts (serialized
  ``CatalogColumnSpec`` payload). May be the empty list when the
  connector cannot introspect columns.
* ``ts`` is the entry timestamp at which the per-table catalog was
  imported; tz-aware on both Postgres (``TIMESTAMPTZ``) and SQLite
  (``DATETIME``).

Backend portability: ``DateTime(timezone=True)`` compiles to
``TIMESTAMPTZ`` on Postgres and ``DATETIME`` on SQLite, matching the
pattern from v014/v015/v016/v021/v022/v023/v024/v025/v026/v027/v028.
``columns`` uses ``JSON`` so the per-column list round-trips byte-
identically across both dialects (JSONB on Postgres, JSON-as-TEXT on
SQLite).

Idempotency: ``checkfirst=True`` on ``Table.create``. Forward-only
per the projections/migrations doctrine — no ``down`` method.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
)


_TABLE_NAME: str = "projection_catalog_tables"


def _build_table() -> Table:
    """Construct the projection_catalog_tables Table on a fresh MetaData.

    Building a fresh MetaData on each call keeps the migration usable
    across multiple test engines without ``InvalidRequestError: Table
    is already defined`` (mirrors the
    v016/v021/v022/v023/v024/v025/v026/v027/v028 pattern). Production
    runs apply once per boot per engine, so the fresh MetaData has no
    runtime cost.

    Composite PK ``(company_id, source_id, table_id, snapshot_hash)``
    keeps each snapshot's table set isolated. Two secondary indexes
    cover the dominant read patterns:

    * ``(company_id, source_id)`` — "all tables for this source across
      snapshots" (L2 TableSet baseline/current fetch).
    * ``(company_id, snapshot_hash)`` — "all tables in this snapshot"
      (L8 SchemaShape per-snapshot column lookup).
    """
    metadata = MetaData()
    return Table(
        _TABLE_NAME,
        metadata,
        Column("company_id", String, primary_key=True, nullable=False),
        Column("source_id", String, primary_key=True, nullable=False),
        Column("table_id", String, primary_key=True, nullable=False),
        Column("snapshot_hash", String, primary_key=True, nullable=False),
        Column("columns", JSON, nullable=False),
        Column("ts", DateTime(timezone=True), nullable=False),
        Index(
            "ix_catalog_tables_source",
            "company_id",
            "source_id",
        ),
        Index(
            "ix_catalog_tables_snapshot",
            "company_id",
            "snapshot_hash",
        ),
    )


def _create(sync_conn: Any) -> None:
    """Idempotent CREATE TABLE for projection_catalog_tables.

    Builds a fresh MetaData + Table each call to stay compatible with
    multi-engine test suites. ``checkfirst=True`` short-circuits on
    re-apply so the migration is byte-stable across boots.
    """
    _build_table().create(sync_conn, checkfirst=True)


class Migration:
    version: int = 29
    description: str = (
        "create projection_catalog_tables — catalog-mirror Wave 2 "
        "Sub-wave A substrate for per-table column metadata "
        "(unblocks L2 TableSet + L8 SchemaShape productivity); "
        "composite PK (company_id, source_id, table_id, snapshot_hash)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(_create)
