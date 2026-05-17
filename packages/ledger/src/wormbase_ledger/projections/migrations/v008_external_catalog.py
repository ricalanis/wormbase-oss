"""v008 — create ``projection_external_catalog``.

Materialized view of ``external_catalog_imported`` ledger entries:
one row per (source_id, snapshot_hash) catalog snapshot. The W5a
catalog-mirror drift-detection Reactivity reads the latest row per
source_id and compares ``snapshot_hash`` against the freshly-discovered
snapshot to decide whether to emit ``external_catalog_drift_detected``.

Phase 0 spike findings baked in:
    * ``import_mode`` distinguishes ``initial`` (first mirror of a freshly
      connected source) from ``refresh`` (periodic re-discover pass) so the
      projection renders onboarding events distinctly from steady-state
      drift checks.

Ported from ``packages/ledger/migrations/v005_external_catalog.sql``
(Wave 1 Task 4 raw-SQL form) to match the canonical Python migration
runner at ``wormbase_ledger.projections.migrate``. Renumbered from
v005 -> v008 to extend the existing monotonic v001-v007 sequence
without collision.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.

Backend portability: SQLAlchemy generic types compile to native
``UUID`` + ``TIMESTAMPTZ`` on Postgres and fall back to ``CHAR(32)`` +
``DATETIME`` on SQLite (tests). The ``CHECK (import_mode IN ...)``
constraint is expressed as a SQLAlchemy ``CheckConstraint`` so it is
emitted uniformly on both backends.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    func,
)


_metadata = MetaData()

projection_external_catalog = Table(
    "projection_external_catalog",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=False),
    Column("source_kind", String, nullable=False),
    Column("snapshot_hash", String, nullable=False),
    Column("table_count", Integer, nullable=False),
    Column("edge_count", Integer, nullable=False),
    Column("metric_count", Integer, nullable=False),
    Column("import_mode", String, nullable=False),
    Column(
        "imported_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint(
        "import_mode IN ('initial', 'refresh')",
        name="ck_external_catalog_import_mode",
    ),
    Index(
        "idx_external_catalog_source",
        "source_id",
        "imported_at",
    ),
    Index(
        "idx_external_catalog_company",
        "company_id",
        "imported_at",
    ),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_external_catalog.create(conn, checkfirst=True)


class Migration:
    version: int = 8
    description: str = (
        "create projection_external_catalog for catalog-mirror drift detection"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
