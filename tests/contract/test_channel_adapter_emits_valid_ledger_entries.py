"""L3 contract: channel-adapter parser → ledger entries validate.

Round-trip a fixture session JSONL line through the parser and the
``LedgerWriter`` and assert that:

1. Every emitted ledger entry has ``kind`` ∈ ``ALL_KINDS``.
2. The ``args`` dict in the canonical ``execute`` entry validates
   against the corresponding Pydantic payload model
   (``ChatReceivedPayload`` / ``ChatSentPayload``) without losing or
   gaining fields.
3. The ``message_id`` and ``channel_id`` in the entry match what the
   parser pulled from the OpenClaw envelope (i.e. parser → adapter →
   ledger is information-preserving).

This is the contract that locks the channel-adapter to the ledger's
wire types; if either side drifts, the test fails before integration.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    ChatSentEvent,
    parse_session_line,
)
from wormbase_channel_adapter.writer import LedgerWriter
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    ALL_KINDS,
    ChatReceivedPayload,
    ChatSentPayload,
)


# ---------------------------------------------------------------------------
# Fixture lines — inlined here (rather than imported from the
# channel-adapter package's conftest) because pytest scopes per-package
# conftests to that package, and this contract test is a sibling, not a
# child, of that package. Keeping them in one place would silently drift
# from the wire shape; instead we keep a frozen sample here and trust
# `test_ledger_chat_received_pydantic_to_ts.py` to catch payload-side
# drift.
# ---------------------------------------------------------------------------


_INBOUND_USER_TEXT = """[Bootstrap pending]
Please read BOOTSTRAP.md from the workspace and follow it before replying normally.

System: [2026-04-25 21:34:05 UTC] Slack message in #todo-baseworm from Ricardo Alanís: <@U0AUSATGUB1> (WormBase) hello

Conversation info (untrusted metadata):
```json
{
  "chat_id": "channel:C0B06MCSLQ1",
  "message_id": "1777152782.692639",
  "reply_to_id": "1777152782.692639",
  "sender_id": "U0AV4C8TTEZ",
  "conversation_label": "#todo-baseworm",
  "sender": "Ricardo Alanís",
  "timestamp": "Sat 2026-04-25 21:33 UTC",
  "group_subject": "#todo-baseworm",
  "group_space": "T0AV1D44GLT",
  "is_group_chat": true,
  "was_mentioned": true
}
```

Sender (untrusted metadata):
```json
{
  "label": "Ricardo Alanís (U0AV4C8TTEZ)",
  "id": "U0AV4C8TTEZ",
  "name": "Ricardo Alanís"
}
```

<@U0AUSATGUB1> (WormBase) hello
"""


def _inbound_line() -> str:
    return (
        json.dumps(
            {
                "type": "message",
                "id": "beaf55cd",
                "parentId": "8b37e230",
                "timestamp": "2026-04-25T21:36:13.978Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": _INBOUND_USER_TEXT}],
                    "timestamp": 1777152973875,
                },
            }
        )
        + "\n"
    )


def _outbound_line() -> str:
    return (
        json.dumps(
            {
                "type": "message",
                "id": "0ff0bc72",
                "parentId": "21da0df6",
                "timestamp": "2026-04-25T21:36:36.167Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Hey. I just came online."}
                    ],
                    "stopReason": "stop",
                    "api": "ollama",
                    "provider": "ollama",
                    "model": "kimi-k2.6:cloud",
                    "usage": {"input": 12609, "output": 195, "totalTokens": 12804},
                    "timestamp": 1777152996153,
                },
            }
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


_SESSION_ID = "48d6fdc0-cd44-411b-860d-7cb43e994dd0"


@pytest.mark.asyncio
async def test_inbound_line_emits_validated_chat_received_entry() -> None:
    event = parse_session_line(_inbound_line(), _SESSION_ID)
    assert isinstance(event, ChatReceivedEvent)

    ledger = InMemoryLedger()
    company_id = uuid4()
    writer = LedgerWriter(ledger, company_id)
    result = await writer.emit(event)
    assert result.entry_ids, "writer returned no entry ids"

    rows = await ledger.fetch(company_id)
    # Every row's `kind` must be a registered EntryPayload kind.
    for r in rows:
        assert r["kind"] in ALL_KINDS, r["kind"]

    # The execute entry's args must validate as ChatReceivedPayload.
    execs = [r for r in rows if r["kind"] == "execute"]
    assert len(execs) == 1
    args = execs[0]["payload"]["args"]
    payload = ChatReceivedPayload.model_validate(args)
    # Field identity: round-trip preserves every key.
    assert set(payload.model_dump().keys()) == set(args.keys())
    # Information preservation: parser fields land in the payload.
    assert payload.channel_id == event.channel_id
    assert payload.message_id == event.message_id
    assert payload.text == event.text


@pytest.mark.asyncio
async def test_outbound_line_emits_validated_chat_sent_entry() -> None:
    inbound = parse_session_line(_inbound_line(), _SESSION_ID)
    assert isinstance(inbound, ChatReceivedEvent)
    outbound = parse_session_line(
        _outbound_line(), _SESSION_ID,
        last_inbound_message_id=inbound.message_id,
    )
    assert isinstance(outbound, ChatSentEvent)

    ledger = InMemoryLedger()
    company_id = uuid4()
    writer = LedgerWriter(ledger, company_id)
    await writer.emit(outbound)

    rows = await ledger.fetch(company_id)
    execs = [r for r in rows if r["kind"] == "execute"]
    assert execs, "no execute entry written"
    args = execs[0]["payload"]["args"]
    payload = ChatSentPayload.model_validate(args)
    assert payload.text == outbound.text
    assert payload.in_reply_to == inbound.message_id
