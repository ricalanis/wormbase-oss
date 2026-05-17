"""v007 migration — projection_topics.

Phase 2 Task 2B (Topic Synthesis Real Implementation):

The ``projection_topics`` table is the silver-conversations layer that
backs the future /topics dashboard tab (Phase 3, validation gap P2.3).
Folded from ``topic_proposed`` ledger entries written by the
production ``TopicSynthesisReactivity``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v007_projection_topics import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "tenant_id",
    "topic_id",
    "label",
    "cluster_signature",
    "cluster_size",
    "member_message_ids",
    "first_seen_at",
    "last_seen_at",
    "confidence",
    "served_by",
    "last_updated_seq",
}


@pytest.mark.asyncio
async def test_v007_creates_projection_topics_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Idempotent re-apply — must not raise.
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("projection_topics")}
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v007_primary_key_is_compound() -> None:
    """PK is (tenant_id, topic_id) for per-tenant per-topic uniqueness."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint("projection_topics")
        )
    assert set(pk["constrained_columns"]) == {"tenant_id", "topic_id"}


@pytest.mark.asyncio
async def test_v007_tenant_index_present() -> None:
    """ix_projection_topics_tenant lets /topics list per-tenant cheaply."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_topics")
        )
    names = {i["name"] for i in idxs}
    assert "ix_projection_topics_tenant" in names


def test_v007_registered_in_canonical_migrations() -> None:
    """V007ProjectionTopicsMigration is in the canonical MIGRATIONS list,
    monotonic and gap-free, with no version-7 duplicates."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 7 in versions, f"expected v7 present; got {versions}"
    # No gaps.
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
