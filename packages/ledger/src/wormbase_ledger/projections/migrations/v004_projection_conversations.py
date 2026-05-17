"""v004 — create ``projection_conversations``.

Closes the validation-gap doc P1.7: the conversation lake has been
aspirational since the principles doc; this migration makes it a real
projected table. ``ConversationSource`` reads from this table for
``recent_window()`` and the `MaintainableSource` methods.

Schema is the canonical chat row: one entry per inbound message, keyed
on (company_id, channel_id, message_id). Carries enough fields for the
maintainer's drift / staleness / lineage work without dragging the full
raw event payload (which stays in the ledger).

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via SQLAlchemy's
``checkfirst=True`` on ``Table.create``.
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Uuid,
)


_metadata = MetaData()

projection_conversations = Table(
    "projection_conversations",
    _metadata,
    Column("company_id", Uuid(as_uuid=True), primary_key=True),
    Column("channel_id", String(128), primary_key=True),
    Column("message_id", String(128), primary_key=True),
    Column("sender_person", Uuid(as_uuid=True), nullable=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("text", String, nullable=False),
    Column("classification", String(32), nullable=False),
    Column("domain_id", Uuid(as_uuid=True), nullable=True),
    Column("thread_root_message_id", String(128), nullable=True),
    Column("platform", String(32), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_conversations.create(conn, checkfirst=True)


class Migration:
    version: int = 4
    description: str = "create projection_conversations"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
