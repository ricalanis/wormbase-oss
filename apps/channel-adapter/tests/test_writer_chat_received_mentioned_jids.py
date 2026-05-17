"""Tests for mentioned_jids threading through LedgerWriter._emit_chat_received
(Wave B1.1, 2026-05-06).

B1 left the predicate forward-compat: ``MentionsWorm`` reads
``args.mentioned_jids`` (or the canonical Baileys nesting under
``args.payload``) but the writer dropped both at the writer boundary.
This wave threads ``mentioned_jids`` through the canonical
``ChatReceivedPayload`` so the predicate evaluates correctly on real
ledger entries (no payload-snooping required).

Pinned contract:

* Writer threads ``ChatReceivedEvent.mentioned_jids`` into
  ``ChatReceivedPayload.mentioned_jids``; the field surfaces on the
  execute.args under the key ``"mentioned_jids"``.
* When the event leaves ``mentioned_jids=None`` (Slack/Discord/Teams
  default), the field defaults to ``None`` on the payload — back-compat
  for adapters that pre-date this wave.
* Slack write-path is byte-identical pre/post: every existing
  Slack-shaped emit produces the same args (modulo the additive
  ``"mentioned_jids": None`` key from the Pydantic dump, which the
  field's ``None`` default makes safe per Schema-Evolution Doctrine
  Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload

from wormbase_channel_adapter.parser import ChatReceivedEvent
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def _executes(rows: list[dict], tool: str) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


def _make_whatsapp_event(
    *,
    mentioned_jids: list[str] | None,
    msg_id: str = "msgWA001",
    channel_id: str = "5511999999999@s.whatsapp.net",
) -> ChatReceivedEvent:
    """Build a WhatsApp-shaped ChatReceivedEvent with custom mentioned_jids."""
    return ChatReceivedEvent(
        kind="chat_received",
        session_id=channel_id,
        event_id=msg_id,
        ts=datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC),
        channel_id=channel_id,
        message_id=msg_id,
        sender_id="5511777777777@s.whatsapp.net",
        sender_label="Test User",
        text="hey @worm what's the latest revenue?",
        conversation_label="DM",
        delivery_mode="push",
        platform_ts=datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC),
        history_sync_id=None,
        mentioned_jids=mentioned_jids,
    )


def _make_slack_event() -> ChatReceivedEvent:
    """Build a Slack-shaped event WITHOUT mentioned_jids (the default)."""
    return ChatReceivedEvent(
        kind="chat_received",
        session_id="sess-slack",
        event_id="evt-slack-1",
        ts=datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC),
        channel_id="channel:C0B06MCSLQ1",
        message_id="1777152782.692639",
        sender_id="U0AV4C8TTEZ",
        sender_label="Ricardo Alanís",
        text="hey @worm",
        conversation_label="#todo-baseworm",
    )


# ---------------------------------------------------------------------------
# 1. mentioned_jids list → field surfaces on execute.args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mentioned_jids_list_surfaces_in_execute_args(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """A WhatsApp-shaped event with mentioned_jids → the writer threads
    the list into ChatReceivedPayload.mentioned_jids and it surfaces
    on the execute.args dict.
    """
    bot_jid = "5511888888888@s.whatsapp.net"
    other_jid = "5511666666666@s.whatsapp.net"
    event = _make_whatsapp_event(mentioned_jids=[bot_jid, other_jid])
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(execs) == 1
    args = execs[0]["payload"]["args"]
    assert args["mentioned_jids"] == [bot_jid, other_jid]


@pytest.mark.asyncio
async def test_mentioned_jids_empty_list_round_trips(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """An empty list (WhatsApp message without mentions) round-trips as
    an empty list — distinct from None (non-WhatsApp adapter)."""
    event = _make_whatsapp_event(mentioned_jids=[])
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "channel_adapter.emit_chat_received")
    args = execs[0]["payload"]["args"]
    assert args["mentioned_jids"] == []


# ---------------------------------------------------------------------------
# 2. mentioned_jids=None (Slack/Discord/Teams default) → None on the args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mentioned_jids_none_default_round_trips(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """A Slack-shaped event leaves mentioned_jids unset (=None default).
    The writer surfaces ``"mentioned_jids": None`` on the args dict —
    additive Pydantic field, back-compat per doctrine Rule 2.
    """
    event = _make_slack_event()
    assert event.mentioned_jids is None  # default
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "channel_adapter.emit_chat_received")
    args = execs[0]["payload"]["args"]
    assert args.get("mentioned_jids") is None


@pytest.mark.asyncio
async def test_explicit_mentioned_jids_none_round_trips(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Explicit mentioned_jids=None on a WhatsApp shape behaves the same
    as Slack's default — the field is None on the args."""
    event = _make_whatsapp_event(mentioned_jids=None)
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "channel_adapter.emit_chat_received")
    args = execs[0]["payload"]["args"]
    assert args.get("mentioned_jids") is None


# ---------------------------------------------------------------------------
# 3. Existing emit_chat_received contract still holds (back-compat).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_compat_existing_chat_received_pevr_cycle(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The PEVR cycle is unchanged — 4 entries, active_probabilistic
    quadrant — when mentioned_jids is None (the existing contract)."""
    event = _make_slack_event()
    result = await writer.emit(event)
    assert result is not None
    assert len(result.entry_ids) == 4

    rows = await writer._ledger.fetch(company_id)
    assert [r["kind"] for r in rows] == [
        "propose", "execute", "verify", "resolve",
    ]
    assert all(r["quadrant"] == "active_probabilistic" for r in rows)


@pytest.mark.asyncio
async def test_args_validate_against_chat_received_payload(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The execute.args still validates against ChatReceivedPayload —
    the additive field doesn't break model_validate."""
    bot_jid = "5511888888888@s.whatsapp.net"
    event = _make_whatsapp_event(mentioned_jids=[bot_jid])
    await writer.emit(event)

    rows = await writer._ledger.fetch(company_id)
    execs = _executes(rows, "channel_adapter.emit_chat_received")
    args = execs[0]["payload"]["args"]
    payload = ChatReceivedPayload.model_validate(args)
    assert payload.mentioned_jids == [bot_jid]


@pytest.mark.asyncio
async def test_pre_provenance_args_still_validate_back_compat() -> None:
    """A pre-this-wave entry (no ``mentioned_jids`` key) still
    model_validate's cleanly — Schema-Evolution Doctrine Rule 2 honored.
    """
    pre_provenance_args = {
        "channel_id": "channel:C0B06MCSLQ1",
        "message_id": "1777152782.692639",
        "sender_person": "00000000-0000-0000-0000-000000000001",
        "text": "hi",
        "classification": "internal",
        # mentioned_jids omitted entirely (pre-this-wave shape)
    }
    payload = ChatReceivedPayload.model_validate(pre_provenance_args)
    assert payload.mentioned_jids is None
