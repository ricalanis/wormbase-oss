"""Lock the MaintainableSource shape on ConversationSource."""
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
from wormbase_lake_maintainer.protocols import MaintainableSource


def _make_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_conversation_source_implements_maintainable() -> None:
    engine = _make_engine()
    async with engine.begin() as conn:
        await V004().up(conn)
    src = ConversationSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    assert isinstance(src, MaintainableSource)


@pytest.mark.asyncio
async def test_staleness_flips_when_last_message_is_old() -> None:
    engine = _make_engine()
    async with engine.begin() as conn:
        await V004().up(conn)
    company = uuid4()
    long_ago = datetime.now(UTC) - timedelta(hours=48)
    async with engine.begin() as conn:
        await conn.execute(insert(projection_conversations), [dict(
            company_id=company, channel_id="C1", message_id="m1",
            sender_person=None, ts=long_ago, text="old",
            classification="internal", domain_id=None,
            thread_root_message_id=None, platform="slack",
            ingested_at=long_ago,
        )])
    src = ConversationSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
    )
    report = await src.staleness_signal()
    assert report.stale is True


@pytest.mark.asyncio
async def test_staleness_clean_when_no_messages_ingested_yet() -> None:
    """Empty channel set returns stale=True so Reactivity probes immediately."""
    engine = _make_engine()
    async with engine.begin() as conn:
        await V004().up(conn)
    src = ConversationSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    report = await src.staleness_signal()
    assert report.stale is True
    assert report.last_seen is None


@pytest.mark.asyncio
async def test_detect_drift_no_baseline_returns_no_drift() -> None:
    engine = _make_engine()
    async with engine.begin() as conn:
        await V004().up(conn)
    src = ConversationSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    report = await src.detect_drift()
    assert report.drifted is False


@pytest.mark.asyncio
async def test_detect_drift_flags_new_topic_cluster() -> None:
    engine = _make_engine()
    async with engine.begin() as conn:
        await V004().up(conn)
    company = uuid4()
    async with engine.begin() as conn:
        await conn.execute(insert(projection_conversations), [dict(
            company_id=company, channel_id="C1", message_id="m1",
            sender_person=None, ts=datetime.now(UTC), text="x",
            classification="pii", domain_id=None,
            thread_root_message_id=None, platform="slack",
            ingested_at=datetime.now(UTC),
        )])
    src = ConversationSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
        baseline_topic_keys=frozenset({"internal"}),
    )
    report = await src.detect_drift()
    assert report.drifted is True
    assert "pii" in report.reason
