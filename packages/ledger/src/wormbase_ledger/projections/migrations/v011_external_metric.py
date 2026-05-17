"""v011 — create ``projection_external_metric``.

One row per imported semantic-layer metric definition, folded from
``external_metric_imported`` ledger entries. Normalized shape across
dbt MetricFlow / Cube / Malloy / LookML so downstream KPI and chat
surfaces can wire to the canonical metric name without re-deriving
the expression each time.

``expression`` / ``time_grain`` / ``description`` are nullable —
upstream catalogs differ on which fields they expose, and the
catalog-mirror data plane should not drop a metric just because one
optional field is missing.

``dimensions`` stores the list of dimensional grouping references.
Stored as ``JSON`` rather than a native ``TEXT[]`` so the projection
is byte-identical across Postgres (production) and SQLite (tests) —
the same pattern v001 uses for ``projection_memory.tags`` and
``projection_topics.member_message_ids``. The pydantic payload's
``dimensions: tuple[str, ...]`` round-trips through JSON list shape
losslessly.

Ported from ``packages/ledger/migrations/v008_external_metric.sql``
(Wave 1 Task 4 raw-SQL form) to match the canonical Python migration
runner at ``wormbase_ledger.projections.migrate``. Renumbered from
v008 -> v011 to extend the existing monotonic v001-v007 sequence
without collision.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
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

projection_external_metric = Table(
    "projection_external_metric",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("company_id", Uuid(as_uuid=True), nullable=False),
    Column("source_id", Uuid(as_uuid=True), nullable=False),
    Column("name", String, nullable=False),
    Column("expression", String, nullable=True),
    Column("time_grain", String, nullable=True),
    Column(
        "dimensions",
        JSON,
        nullable=False,
        default=list,
    ),
    Column("description", String, nullable=True),
    Column(
        "imported_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Index(
        "uq_external_metric_source_name",
        "source_id",
        "name",
        unique=True,
    ),
    Index(
        "idx_external_metric_company",
        "company_id",
        "imported_at",
    ),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_external_metric.create(conn, checkfirst=True)


class Migration:
    version: int = 11
    description: str = (
        "create projection_external_metric for semantic-layer metric definitions"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
