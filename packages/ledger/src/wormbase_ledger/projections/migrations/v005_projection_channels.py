"""v005 — create ``projection_channels``.

Per chat-worm Wave B (D13 in the orchestration doc): talkativeness is
per-channel policy-applied state, not constructor config. This migration
makes the projection table real so:
  * the dashboard's /channels tab can write policy:channel_talkativeness
    edits and see them reflected in the worm's behavior on the next event
  * InterjectionBudgetReactivity has a place to materialise daily-budget
    consumption (replacing the inline ledger fold in InterjectionGate.allow)
  * ChatStore.read_policy can serve a fast Postgres read instead of folding
    policy_applied entries every call

Schema mirrors the column shape documented in
``docs/superpowers/plans/2026-05-03-chat-worm-extraction.md`` Block A.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Uuid,
)


_metadata = MetaData()

projection_channels = Table(
    "projection_channels",
    _metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("channel_id", String(128), primary_key=True),
    Column("talkativeness", String(16), nullable=False, default="responsive"),
    Column("daily_interjection_budget", BigInteger, nullable=False, default=3),
    Column("last_set_by", Uuid(as_uuid=True), nullable=True),
    Column("last_set_at", DateTime(timezone=True), nullable=True),
    Column("last_interjection_count", BigInteger, nullable=False, default=0),
    Column("last_interjection_day", String(10), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=False, default=0),
    Index("ix_projection_channels_tenant", "tenant_id"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_channels.create(conn, checkfirst=True)


class Migration:
    version: int = 5
    description: str = "create projection_channels"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
