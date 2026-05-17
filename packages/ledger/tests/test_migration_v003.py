"""v003 migration — projection_sources.last_seen."""
from __future__ import annotations

import pytest
from sqlalchemy import (
    Column, DateTime, LargeBinary, MetaData, String, Table, Uuid, inspect,
)
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations.v003_source_last_seen import Migration


def _v002_projection_sources(metadata: MetaData) -> Table:
    """The pre-v003 column shape of projection_sources, used as a test fixture."""
    return Table(
        "projection_sources",
        metadata,
        Column("company_id", Uuid(as_uuid=True), primary_key=True),
        Column("source_id", Uuid(as_uuid=True), primary_key=True),
        Column("status", String(32), nullable=False),
        Column("kind", String(32), nullable=False),
        Column("uri", String(1024), nullable=False),
        Column("domain_id", Uuid(as_uuid=True), nullable=True),
        Column("classification", String(32), nullable=False),
        Column("added_by_person", Uuid(as_uuid=True), nullable=True),
        Column("added_via_flow", String(64), nullable=False),
        Column("added_at", DateTime(timezone=True), nullable=False),
        Column("last_entry_hash", LargeBinary(32), nullable=False),
    )


@pytest.mark.asyncio
async def test_v003_adds_last_seen_column_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    md = MetaData()
    _v002_projection_sources(md)
    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)
    # First apply
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Second apply — must be a no-op (idempotent)
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Inspect
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("projection_sources")}
        )
    assert "last_seen" in cols


@pytest.mark.asyncio
async def test_v003_last_seen_is_nullable() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    md = MetaData()
    _v002_projection_sources(md)
    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"]: c for c in inspect(sc).get_columns("projection_sources")}
        )
    assert cols["last_seen"]["nullable"] is True
