"""PostgresLakeStore: thin wrapper over MedallionCascade + SQLAlchemy."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.schema import metadata as ledger_metadata, projection_sources
from wormbase_lake_maintainer.lake_store import PostgresLakeStore
from wormbase_lake_maintainer.protocols import LakeStore


async def _engine():
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.begin() as conn:
        await conn.run_sync(ledger_metadata.create_all)
    return e


@pytest.mark.asyncio
async def test_postgres_lake_store_implements_protocol() -> None:
    cascade = MagicMock()
    cascade._write_bronze = AsyncMock()
    cascade._write_silver = AsyncMock()
    cascade._write_gold = AsyncMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    assert isinstance(store, LakeStore)


@pytest.mark.asyncio
async def test_write_bronze_delegates_to_cascade() -> None:
    """Avoid worm-core import (circular dep) — pass a MagicMock for profile."""
    cascade = MagicMock()
    cascade._write_bronze = AsyncMock()
    cascade._write_silver = AsyncMock()
    cascade._write_gold = AsyncMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    company = uuid4()
    source = uuid4()
    profile = MagicMock()  # structural stand-in for BronzeProfile
    await store.write_bronze(
        company_id=company, source_id=source, profile=profile,
    )
    cascade._write_bronze.assert_awaited_once_with(company, source, profile)


@pytest.mark.asyncio
async def test_write_silver_delegates_to_cascade() -> None:
    cascade = MagicMock()
    cascade._write_bronze = AsyncMock()
    cascade._write_silver = AsyncMock()
    cascade._write_gold = AsyncMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    company = uuid4()
    source = uuid4()
    columns = [MagicMock(), MagicMock()]  # stand-ins for InferredColumn
    join_candidates = [uuid4()]
    await store.write_silver(
        company_id=company, source_id=source,
        columns=columns, join_candidates=join_candidates,
    )
    cascade._write_silver.assert_awaited_once_with(
        company, source, columns, join_candidates,
    )


@pytest.mark.asyncio
async def test_write_gold_delegates_to_cascade() -> None:
    cascade = MagicMock()
    cascade._write_bronze = AsyncMock()
    cascade._write_silver = AsyncMock()
    cascade._write_gold = AsyncMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    company = uuid4()
    source = uuid4()
    gold = MagicMock()  # structural stand-in for GoldArtifact
    await store.write_gold(
        company_id=company, source_id=source, gold=gold,
    )
    cascade._write_gold.assert_awaited_once_with(company, source, gold)


@pytest.mark.asyncio
async def test_read_layer_bronze_returns_projection_rows() -> None:
    """SQLite/aiosqlite drops tzinfo on DateTime(timezone=True); coerce in test fixture."""
    engine = await _engine()
    company = uuid4()
    src_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(insert(projection_sources), [dict(
            company_id=company, source_id=src_id,
            status="confirmed", kind="csv_local",
            uri="file:///tmp/x.csv", domain_id=None,
            classification="internal", added_by_person=None,
            added_via_flow="dashboard_form",
            added_at=datetime.now(UTC),
            last_entry_hash=b"\x00" * 32,
            last_seen=None,
        )])
    cascade = MagicMock()
    cascade._write_bronze = AsyncMock()
    cascade._write_silver = AsyncMock()
    cascade._write_gold = AsyncMock()
    store = PostgresLakeStore(engine=engine, cascade=cascade)
    rows = []
    async for row in store.read_layer(company_id=company, layer="bronze"):
        rows.append(row)
    assert len(rows) == 1
    assert rows[0]["uri"] == "file:///tmp/x.csv"


@pytest.mark.asyncio
async def test_read_layer_unknown_raises() -> None:
    cascade = MagicMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    with pytest.raises(ValueError, match="unknown layer"):
        async for _ in store.read_layer(
            company_id=uuid4(), layer="quartz",  # type: ignore[arg-type]
        ):
            pass


@pytest.mark.asyncio
async def test_read_layer_silver_raises_not_implemented() -> None:
    """Silver is deferred to v1.5; v1 raises explicitly rather than aliasing to bronze."""
    cascade = MagicMock()
    store = PostgresLakeStore(engine=await _engine(), cascade=cascade)
    with pytest.raises(NotImplementedError, match="silver: deferred to v1.5"):
        async for _ in store.read_layer(
            company_id=uuid4(), layer="silver",
        ):
            pass
