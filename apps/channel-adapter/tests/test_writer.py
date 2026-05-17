"""Tests for LedgerWriter against InMemoryLedger.

We assert:
  * Every emit() produces 4 hash-chained ledger entries (PEVR cycle).
  * The execute row's payload.args matches the public Pydantic model
    so downstream projectors can ``ChatReceivedPayload.model_validate``.
  * Quadrant is 'active_probabilistic' (per CLAUDE.md two-speeds-four-
    quadrants rule for chat traffic).
  * chat_sent carries speech_act='answer' (Wave-2 review resolution).
  * The hash chain stays intact across multiple emits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload, ChatSentPayload

from wormbase_channel_adapter.parser import ChatReceivedEvent, ChatSentEvent
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter, slack_user_to_person_uuid


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def make_received_event() -> ChatReceivedEvent:
    return ChatReceivedEvent(
        kind="chat_received",
        session_id="sess-A",
        event_id="evt-1",
        ts=datetime(2026, 4, 25, 21, 36, 13, tzinfo=UTC),
        channel_id="channel:C0B06MCSLQ1",
        message_id="1777152782.692639",
        sender_id="U0AV4C8TTEZ",
        sender_label="Ricardo Alanís",
        text="<@U0AUSATGUB1> hello",
        conversation_label="#todo-baseworm",
    )


def make_sent_event() -> ChatSentEvent:
    return ChatSentEvent(
        kind="chat_sent",
        session_id="sess-A",
        event_id="evt-2",
        ts=datetime(2026, 4, 25, 21, 36, 36, tzinfo=UTC),
        text="Hey. I just came online.",
        in_reply_to="1777152782.692639",
    )


class TestEmitChatReceived:
    @pytest.mark.asyncio
    async def test_emits_pevr_cycle(self, writer: LedgerWriter, company_id: UUID) -> None:
        result = await writer.emit(make_received_event())
        assert len(result.entry_ids) == 4

        rows = await writer._ledger.fetch(company_id)
        assert [r["kind"] for r in rows] == [
            "propose",
            "execute",
            "verify",
            "resolve",
        ]

    @pytest.mark.asyncio
    async def test_quadrant_is_active_probabilistic(
        self, writer: LedgerWriter, company_id: UUID
    ) -> None:
        await writer.emit(make_received_event())
        rows = await writer._ledger.fetch(company_id)
        assert all(r["quadrant"] == "active_probabilistic" for r in rows)

    @pytest.mark.asyncio
    async def test_execute_payload_matches_chat_received_schema(
        self, writer: LedgerWriter, company_id: UUID
    ) -> None:
        await writer.emit(make_received_event())
        rows = await writer._ledger.fetch(company_id)
        execute = next(r for r in rows if r["kind"] == "execute")
        # The execute payload's ``args`` field should be a valid
        # ChatReceivedPayload — no schema drift.
        args = execute["payload"]["args"]
        payload = ChatReceivedPayload.model_validate(args)
        assert payload.channel_id == "channel:C0B06MCSLQ1"
        assert payload.message_id == "1777152782.692639"
        assert payload.text == "<@U0AUSATGUB1> hello"
        assert payload.sender_person == slack_user_to_person_uuid("U0AV4C8TTEZ")

    @pytest.mark.asyncio
    async def test_propose_target_kind_is_chat_received(
        self, writer: LedgerWriter, company_id: UUID
    ) -> None:
        await writer.emit(make_received_event())
        rows = await writer._ledger.fetch(company_id)
        propose = rows[0]
        assert propose["payload"]["target_kind"] == "chat_received"
        assert propose["payload"]["proposed_by"] == "channel-adapter"


class TestEmitChatSent:
    @pytest.mark.asyncio
    async def test_emits_pevr_cycle(self, writer: LedgerWriter, company_id: UUID) -> None:
        result = await writer.emit(make_sent_event())
        assert len(result.entry_ids) == 4

    @pytest.mark.asyncio
    async def test_payload_carries_speech_act_answer(
        self, writer: LedgerWriter, company_id: UUID
    ) -> None:
        await writer.emit(make_sent_event())
        rows = await writer._ledger.fetch(company_id)
        execute = next(r for r in rows if r["kind"] == "execute")
        payload = ChatSentPayload.model_validate(execute["payload"]["args"])
        assert payload.speech_act == "answer"
        assert payload.in_reply_to == "1777152782.692639"
        assert payload.attribution["source"] == "openclaw"


class TestChainIntegrity:
    @pytest.mark.asyncio
    async def test_two_emits_produce_eight_entries_with_intact_chain(
        self, writer: LedgerWriter, company_id: UUID
    ) -> None:
        await writer.emit(make_received_event())
        await writer.emit(make_sent_event())

        rows = await writer._ledger.fetch(company_id)
        assert len(rows) == 8
        # Hash chain: each prev_hash matches the previous row's hash.
        for prev, curr in zip(rows, rows[1:], strict=False):
            assert curr["prev_hash"] == prev["hash"]

        report = await writer._ledger.verify(company_id)
        assert report.ok is True
        assert report.entries_checked == 8


class TestSlackUserMapping:
    def test_same_id_same_uuid(self) -> None:
        assert slack_user_to_person_uuid("U123") == slack_user_to_person_uuid("U123")

    def test_different_ids_differ(self) -> None:
        assert slack_user_to_person_uuid("U123") != slack_user_to_person_uuid("U999")

    def test_empty_id_yields_unknown_sentinel(self) -> None:
        a = slack_user_to_person_uuid("")
        b = slack_user_to_person_uuid("")
        assert a == b  # collide on purpose
