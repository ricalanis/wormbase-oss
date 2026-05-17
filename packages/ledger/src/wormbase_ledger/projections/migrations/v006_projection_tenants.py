"""v006 — create ``projection_tenants``.

Phase 1B.A of the multi-tenancy v2 plan
(``docs/superpowers/plans/2026-05-04-multitenancy-v2.md``). The table is
the canonical projection of multi-tenant lifecycle state, folded from
``tenant_signup_initiated`` and ``tenant_signup_completed`` entries
(registered in 1B.B). Status starts at ``pending`` on signup_initiated
and transitions to ``active`` on signup_completed.

The ``demo_visitors`` JSON column carries the magic-link round-robin
state — empty for non-demo tenants.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)


_metadata = MetaData()

projection_tenants = Table(
    "projection_tenants",
    _metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("slug", String(128), nullable=False),
    Column("display_name", String(256), nullable=False),
    Column("signup_source", String(32), nullable=False),
    Column("signup_email", String(255), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("signup_completed_at", DateTime(timezone=True), nullable=True),
    Column("status", String(16), nullable=False),
    Column("demo_visitors", JSON, nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    UniqueConstraint("slug", name="uq_projection_tenants_slug"),
    Index("ix_projection_tenants_status", "status"),
    Index("ix_projection_tenants_signup_source", "signup_source"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_tenants.create(conn, checkfirst=True)


class Migration:
    version: int = 6
    description: str = "create projection_tenants for multi-tenancy v2"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
