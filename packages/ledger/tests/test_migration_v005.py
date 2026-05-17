"""v005 migration — projection_channels."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v005_projection_channels import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "tenant_id",
    "channel_id",
    "talkativeness",
    "daily_interjection_budget",
    "last_set_by",
    "last_set_at",
    "last_interjection_count",
    "last_interjection_day",
    "last_updated_seq",
}


@pytest.mark.asyncio
async def test_v005_creates_projection_channels_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Idempotent re-apply — must not raise.
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("projection_channels")}
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v005_primary_key_is_compound() -> None:
    """PK is (tenant_id, channel_id) for per-tenant per-channel uniqueness."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint("projection_channels")
        )
    assert set(pk["constrained_columns"]) == {"tenant_id", "channel_id"}


@pytest.mark.asyncio
async def test_v005_tenant_index_present() -> None:
    """ix_projection_channels_tenant lets /channels list per-tenant cheaply."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_channels")
        )
    names = {i["name"] for i in idxs}
    assert "ix_projection_channels_tenant" in names


@pytest.mark.asyncio
async def test_v005_nullable_columns() -> None:
    """last_set_by, last_set_at, last_interjection_day are nullable."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"]: c for c in inspect(sc).get_columns("projection_channels")}
        )
    assert cols["last_set_by"]["nullable"] is True
    assert cols["last_set_at"]["nullable"] is True
    assert cols["last_interjection_day"]["nullable"] is True
    # NOT NULL invariants.
    assert cols["talkativeness"]["nullable"] is False
    assert cols["daily_interjection_budget"]["nullable"] is False
    assert cols["last_interjection_count"]["nullable"] is False
    assert cols["last_updated_seq"]["nullable"] is False


def test_v005_registered_in_canonical_migrations() -> None:
    """V005ProjectionChannelsMigration is in the canonical MIGRATIONS list,
    monotonic and gap-free, with no version-5 duplicates."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 5 in versions, f"expected v5 present; got {versions}"
    # No gaps.
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
