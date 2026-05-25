"""Phase 3: gateway-parity contract — OpenClaw and Hermes produce equivalent ChatReceivedEvents.

Per `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md`
§6 Phase 3: "the headline ledger rows should be identical between an
OpenClaw run and a Hermes run of the same scenario (modulo the gateway
attribution string in payload.attribution['source'])."

This module is the **structural** half of that gate: given semantically-
equivalent inbound signals, both gateway-paths inside the channel-adapter
must build a ChatReceivedEvent whose user-visible fields match. The
**live** half (run the 7-beat install-arc scenario end-to-end against a
running Hermes Agent, compare ledger hashes) requires upstream Hermes
to be reachable + actually firing on every inbound — pending the H1
NO-GO resolution. These tests are deterministic regardless.

What "semantically equivalent" means:

- Same sender (Slack user id / WhatsApp phone)
- Same message body
- Same recipient (bot user / bot phone)
- Same wall-clock timestamp

What we ASSERT equal:

- `event.text`
- `event.sender_id` (canonical-form)
- `event.channel_id` (canonical-form OR equivalent within the gateway's
   addressing convention — Hermes uses `hermes-session:<id>` sentinel
   when richer context is absent, OpenClaw uses Slack `C0…` channel ids;
   the parity check is on text+sender+ts being IDENTICAL)
- `event.delivery_mode = "push"`
- `event.ts` within 1ms

What we ALLOW to differ:

- `event.message_id` / `event.event_id` (gateway-specific synthetic
   IDs; the writer dedups on (channel_id, message_id) so identical
   replays within a gateway collapse, but cross-gateway IDs are
   intentionally different — that's the spec's "modulo attribution")
- `event.session_id` (gateway-specific prefix: `hermes:<uuid>` vs
   OpenClaw session UUID from JSONL frame)
- `event.channel_id` shape when the gateway lacks the underlying
   conversation context (Hermes wire-tap may emit
   `hermes-session:<uuid>` sentinel)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from wormbase_channel_adapter.hermes_event_consumer import (
    DEFAULT_PATH,
    HermesEventConsumer,
)
from wormbase_channel_adapter.parser import ChatReceivedEvent


# ---------------------------------------------------------------------------
# Shared inbound fixture — semantically equivalent across gateways
# ---------------------------------------------------------------------------

SHARED_SENDER = "U0AV4C8TTEZ"
SHARED_TEXT = "hola from the install-arc scenario"
SHARED_TS = datetime(2026, 5, 21, 18, 0, 0, tzinfo=UTC)
SHARED_BOT = "B0V4C8TTEZ"
SHARED_SESSION = "5d8efadc-1234-4abc-9def-0123456789ab"


def _hermes_payload(**overrides: Any) -> dict[str, Any]:
    """Wire-tap hook envelope shape."""
    payload: dict[str, Any] = {
        "received_at": SHARED_TS.isoformat(),
        "event_type": "agent:start",
        "tenant": "baseworm",
        "context": {
            "platform": "slack",
            "user_id": SHARED_SENDER,
            "session_id": SHARED_SESSION,
            "message": SHARED_TEXT,
        },
    }
    payload.update(overrides)
    return payload


def _expected_openclaw_event() -> ChatReceivedEvent:
    """The event the OpenClaw path would produce (modeling, not capturing).

    The actual OpenClaw path goes session JSONL → parser → Slack
    Web API fetch for body → ChatReceivedEvent. We model what that
    yields for the SHARED fixture so the parity test has a baseline
    without needing a live OpenClaw container.
    """
    return ChatReceivedEvent(
        kind="chat_received",
        session_id="openclaw-fixture-session",  # gateway-specific
        event_id="openclaw-fixture-event",  # gateway-specific
        ts=SHARED_TS,
        channel_id="C0B06MCSLQ1",  # would be the real Slack channel id
        message_id="1779388595.682",  # would be the Slack ts
        sender_id=SHARED_SENDER,
        sender_label=SHARED_SENDER,
        text=SHARED_TEXT,
        conversation_label="",
        delivery_mode="push",
        platform_ts=SHARED_TS,
        history_sync_id=None,
        mentioned_jids=None,
    )


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------


async def test_hermes_emits_event_with_matching_text_and_sender() -> None:
    """Same inbound → same text + sender across gateways."""
    writer = AsyncMock()
    consumer = HermesEventConsumer(writer=writer)
    app = web.Application()
    app.router.add_post(DEFAULT_PATH, consumer._handle_post)
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=_hermes_payload())
        assert resp.status == 200

    hermes_event = writer.emit.await_args.args[0]
    openclaw_event = _expected_openclaw_event()

    # User-visible field parity — the spec's headline guarantee.
    assert hermes_event.text == openclaw_event.text
    assert hermes_event.sender_id == openclaw_event.sender_id
    assert hermes_event.delivery_mode == openclaw_event.delivery_mode
    assert (
        abs((hermes_event.ts - openclaw_event.ts).total_seconds()) < 0.001
    )


async def test_hermes_synthetic_ids_are_deterministic_per_session() -> None:
    """Same payload posted twice → same synthetic message_id → writer dedups."""
    writer = AsyncMock()
    consumer = HermesEventConsumer(writer=writer)
    app = web.Application()
    app.router.add_post(DEFAULT_PATH, consumer._handle_post)
    payload = _hermes_payload()
    async with TestServer(app) as server, TestClient(server) as client:
        r1 = await client.post(DEFAULT_PATH, json=payload)
        r2 = await client.post(DEFAULT_PATH, json=payload)
        assert r1.status == 200
        assert r2.status == 200

    # Both events have the same message_id (deterministic SHA256 of
    # canonical fields). The writer's dedup absorbs the second arrival
    # in production; here we just verify the contract holds.
    e1 = writer.emit.await_args_list[0].args[0]
    e2 = writer.emit.await_args_list[1].args[0]
    assert e1.message_id == e2.message_id
    assert e1.channel_id == e2.channel_id


async def test_hermes_richer_context_matches_openclaw_addressing() -> None:
    """When the wire-tap hook is extended to include channel_id +
    message_ts, the Hermes event's channel_id matches OpenClaw's
    Slack channel id — closing the parity gap entirely."""
    writer = AsyncMock()
    consumer = HermesEventConsumer(writer=writer)
    app = web.Application()
    app.router.add_post(DEFAULT_PATH, consumer._handle_post)
    payload = _hermes_payload(
        context={
            "platform": "slack",
            "user_id": SHARED_SENDER,
            "session_id": SHARED_SESSION,
            "message": SHARED_TEXT,
            "channel_id": "C0B06MCSLQ1",
            "message_ts": "1779388595.682",
        },
    )
    async with TestServer(app) as server, TestClient(server) as client:
        resp = await client.post(DEFAULT_PATH, json=payload)
        assert resp.status == 200

    hermes_event = writer.emit.await_args.args[0]
    openclaw_event = _expected_openclaw_event()
    assert hermes_event.channel_id == openclaw_event.channel_id
    assert hermes_event.message_id == openclaw_event.message_id


# ---------------------------------------------------------------------------
# Live-Hermes integration test (skipped by default — requires upstream)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Live Hermes Agent gateway required. The Phase 1 spike (H1) returned "
        "NO-GO 2026-04-27: Hermes v0.11.0 fires hooks only on agent-engaged "
        "messages, not every inbound. Re-enable this test when upstream Hermes "
        "ships a hook that fires on every inbound (per the channel-adapter's "
        "lurker contract). Until then, the structural parity tests above are "
        "the verification surface."
    ),
)
async def test_live_hermes_install_arc_scenario_matches_openclaw_hashes() -> None:
    """End-to-end: run the install-arc 7-beat scenario against a live
    Hermes gateway, capture the ledger entries, and assert the
    headline ledger row hashes are identical to an OpenClaw baseline.

    The spec's gold-standard Phase 3 acceptance gate. Skipped by
    default; enabled by a future operator when Hermes upstream
    resolves the hook-coverage issue.
    """
    pytest.fail("This test runs only when WORMBASE_HERMES_LIVE=1.")
