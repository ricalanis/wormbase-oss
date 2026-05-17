"""v007 — create ``projection_topics``.

Phase 2 Task 2B of the Wave H final-level v1 launch (real
implementation of ``TopicSynthesisReactivity``, promoted from the
F.1 stub). The table is the canonical silver-conversations
projection of topic clusters, folded from ``topic_proposed``
entries written by the production Reactivity.

The table backs the future /topics dashboard tab (Phase 3,
validation gap P2.3); this migration lands the substrate so that
in-flight Phase-2 ledger entries already populate the projection
when the tab ships.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` semantics via
SQLAlchemy's ``checkfirst=True`` on ``Table.create``.
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
    Uuid,
)


_metadata = MetaData()

projection_topics = Table(
    "projection_topics",
    _metadata,
    Column("tenant_id", Uuid(as_uuid=True), primary_key=True),
    Column("topic_id", Uuid(as_uuid=True), primary_key=True),
    Column("label", String(256), nullable=False),
    Column("cluster_signature", String(512), nullable=False),
    Column("cluster_size", BigInteger, nullable=False),
    Column("member_message_ids", JSON, nullable=False),  # list[str]
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("confidence", String(8), nullable=False),  # "0.50" stored as str for byte stability
    Column("served_by", String(16), nullable=False),
    Column("last_updated_seq", BigInteger, nullable=False),
    Index("ix_projection_topics_tenant", "tenant_id"),
    Index("ix_projection_topics_last_seen", "tenant_id", "last_seen_at"),
)


def _create(conn) -> None:  # type: ignore[no-untyped-def]
    projection_topics.create(conn, checkfirst=True)


class Migration:
    version: int = 7
    description: str = (
        "create projection_topics for silver-conversations topic clusters"
    )

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_create)
