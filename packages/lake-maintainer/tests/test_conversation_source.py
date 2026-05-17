"""ConversationSource introspection methods."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations.v004_projection_conversations import (
    Migration as V004,
    projection_conversations,
)
from wormbase_lake_maintainer.conversation_source import ConversationSource


@pytest.mark.asyncio
async def test_enumerate_channels_returns_distinct_channel_ids() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V004().up(conn)
    company = uuid4()
    rows = [
        dict(
            company_id=company, channel_id="C1", message_id=f"m{i}",
            sender_person=None, ts=datetime.now(UTC), text=f"hi {i}",
            classification="internal", domain_id=None,
            thread_root_message_id=None, platform="slack",
            ingested_at=datetime.now(UTC),
        )
        for i in range(3)
    ]
    rows.append(dict(rows[0], channel_id="C2", message_id="m99"))
    async with engine.begin() as conn:
        await conn.execute(insert(projection_conversations), rows)
    src = ConversationSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
    )
    channels = await src.enumerate_channels()
    assert sorted(channels) == ["C1", "C2"]


@pytest.mark.asyncio
async def test_recent_window_returns_last_n_messages_in_descending_ts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V004().up(conn)
    company = uuid4()
    base = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(insert(projection_conversations), [
            dict(
                company_id=company, channel_id="C1",
                message_id=f"m{i}", sender_person=None,
                ts=base - timedelta(minutes=i),
                text=f"msg{i}", classification="internal",
                domain_id=None, thread_root_message_id=None,
                platform="slack", ingested_at=base,
            )
            for i in range(10)
        ])
    src = ConversationSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
    )
    window = await src.recent_window(n=3)
    assert len(window) == 3
    assert [m["text"] for m in window] == ["msg0", "msg1", "msg2"]


@pytest.mark.asyncio
async def test_topic_summary_returns_per_classification_counts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V004().up(conn)
    company = uuid4()
    async with engine.begin() as conn:
        await conn.execute(insert(projection_conversations), [
            dict(
                company_id=company, channel_id="C1", message_id=f"m{i}",
                sender_person=None, ts=datetime.now(UTC), text="x",
                classification="internal" if i < 3 else "pii",
                domain_id=None, thread_root_message_id=None,
                platform="slack", ingested_at=datetime.now(UTC),
            )
            for i in range(5)
        ])
    src = ConversationSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
    )
    summary = await src.topic_summary()
    assert summary == {"internal": 3, "pii": 2}
