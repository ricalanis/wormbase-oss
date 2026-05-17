"""v004 migration — projection_conversations."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations.v004_projection_conversations import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "company_id", "channel_id", "message_id", "sender_person",
    "ts", "text", "classification", "domain_id", "thread_root_message_id",
    "platform", "ingested_at",
}


@pytest.mark.asyncio
async def test_v004_creates_projection_conversations_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Idempotent re-apply
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("projection_conversations")}
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v004_primary_key_is_compound() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint("projection_conversations")
        )
    assert set(pk["constrained_columns"]) == {"company_id", "channel_id", "message_id"}
