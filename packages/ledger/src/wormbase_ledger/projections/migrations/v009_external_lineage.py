"""v009 — create ``projection_external_lineage``.

One row per upstream lineage edge per snapshot import — folded from
``external_lineage_imported`` ledger entries written by the catalog-mirror
data plane. Edges are fully-qualified node ids:
e.g. dbt's ``"source.raw.events" -> "model.staging.events"`` or
Snowflake's ``"ACME.RAW.EVENTS" -> "ACME.STAGING.EVENTS"``.

Both ``upstream`` and ``downstream`` indexes are kept so the lineage tab
can render either direction (impact-of-upstream-change vs.
provenance-of-downstream-asset) cheaply.

Ported from ``packages/ledger/migrations/v006_external_lineage.sql``
(Wave 1 Task 4 raw-SQL form) to match the canonical Python migration
runner at ``wormbase_ledger.projections.migrate``. Renumbered from
v006 -> v009 to extend the existing monotonic v001-v007 sequence
without collision.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Uuid,
    func,
)


_metadata = MetaData()

projection_external_lineage = Table(
    "projection_external_lineage",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("upstream", String, nullable=False),
    Column("downstream", String, nullable=False),
    Column(
        "imported_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Index(
        "idx_external_lineage_upstream",
        "company_id",
        "upstream",
    ),
    Index(
        "idx_external_lineage_downstream",
        "company_id",
        "downstream",
    ),
    Index(
        "idx_external_lineage_source",
        "source_id",
        "imported_at",
    ),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_external_lineage.create(conn, checkfirst=True)


class Migration:
    version: int = 9
    description: str = (
        "create projection_external_lineage for upstream lineage edges"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
