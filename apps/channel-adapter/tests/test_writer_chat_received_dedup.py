"""Tests for LedgerWriter._emit_chat_received per-key dedup.

WhatsApp/Baileys replays history on every reconnect; Slack's
stale-fetch path can re-deliver an event after a reconnect. The writer
keys dedup on (channel_id, message_id) with an LRU window of 1024
distinct keys, so the second arrival of the same logical message
returns None (no ledger write) without losing the parser → writer
contract for fresh events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_channel_adapter.parser import ChatReceivedEvent
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def _evt(*, channel: str, mid: str, text: str = "hello") -> ChatReceivedEvent:
    return ChatReceivedEvent(
        kind="chat_received",
        session_id="sess-A",
        event_id=f"evt-{mid}",
        ts=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        channel_id=channel,
        message_id=mid,
        sender_id="U1",
        sender_label="Test User",
        text=text,
        conversation_label="#test",
    )


class TestDedupBehavior:
    @pytest.mark.asyncio
    async def test_same_channel_message_id_pair_dedups(
        self, writer: LedgerWriter, company_id: UUID,
    ) -> None:
        """Second emit of identical (channel, message_id) returns None."""
        first = await writer.emit(_evt(channel="C1", mid="m1"))
        second = await writer.emit(_evt(channel="C1", mid="m1"))
        assert first is not None
        assert second is None
        rows = await writer._ledger.fetch(company_id)
        # Only the first emit produced PEVR (4 entries).
        assert len(rows) == 4

    @pytest.mark.asyncio
    async def test_different_message_ids_both_write(
        self, writer: LedgerWriter, company_id: UUID,
    ) -> None:
        a = await writer.emit(_evt(channel="C1", mid="m1"))
        b = await writer.emit(_evt(channel="C1", mid="m2"))
        assert a is not None
        assert b is not None
        rows = await writer._ledger.fetch(company_id)
        assert len(rows) == 8

    @pytest.mark.asyncio
    async def test_different_channels_same_message_id_both_write(
        self, writer: LedgerWriter, company_id: UUID,
    ) -> None:
        """Different channels are independent dedup keys."""
        a = await writer.emit(_evt(channel="C1", mid="m1"))
        b = await writer.emit(_evt(channel="C2", mid="m1"))
        assert a is not None
        assert b is not None
        rows = await writer._ledger.fetch(company_id)
        assert len(rows) == 8

    @pytest.mark.asyncio
    async def test_provenance_fields_round_trip_via_writer(
        self, writer: LedgerWriter, company_id: UUID,
    ) -> None:
        from wormbase_ledger.entries import ChatReceivedPayload

        platform_ts = datetime(2026, 5, 5, 11, 0, tzinfo=UTC)
        evt = ChatReceivedEvent(
            kind="chat_received",
            session_id="sess-A",
            event_id="evt-X",
            ts=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
            channel_id="C1",
            message_id="m-prov",
            sender_id="U1",
            sender_label="Test",
            text="hello",
            conversation_label="#test",
            delivery_mode="history_sync",
            platform_ts=platform_ts,
            history_sync_id="sync-zzz",
        )
        await writer.emit(evt)
        rows = await writer._ledger.fetch(company_id)
        execute = next(r for r in rows if r["kind"] == "execute")
        payload = ChatReceivedPayload.model_validate(execute["payload"]["args"])
        assert payload.delivery_mode == "history_sync"
        assert payload.platform_ts == platform_ts
        assert payload.history_sync_id == "sync-zzz"


class TestLruEviction:
    @pytest.mark.asyncio
    async def test_lru_evicts_oldest_after_capacity(
        self, writer: LedgerWriter,
    ) -> None:
        """Past 1024 distinct keys, the oldest is evicted; replays then
        write again. The ceiling matters because Baileys can replay
        thousands of historical messages on first connect."""
        # Force a small window so the test is fast and deterministic.
        writer._recent_chat_received_max = 4

        # Fill capacity with 4 distinct keys.
        for i in range(4):
            r = await writer.emit(_evt(channel="C1", mid=f"m{i}"))
            assert r is not None

        # Replaying m0 right now → still in window → dedup returns None.
        replay = await writer.emit(_evt(channel="C1", mid="m0"))
        assert replay is None

        # Add a 5th distinct key — this evicts m0 from the LRU.
        new = await writer.emit(_evt(channel="C1", mid="m4"))
        assert new is not None

        # Now m0 has fallen out — replaying it writes again.
        post_evict = await writer.emit(_evt(channel="C1", mid="m0"))
        assert post_evict is not None
