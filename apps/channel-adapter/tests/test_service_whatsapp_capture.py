"""Tests for WhatsAppLogCapture (Phase 3 of 2026-05-05 plan).

Mirrors :mod:`test_service_global_log_capture` for the WhatsApp wire-up.
The capture object turns a bare jid (from OpenClaw's
``whatsapp: allow channel <jid>`` log line) into:

  * one ``chat_received`` PEVR cycle per inbound message (via
    LedgerWriter._emit_chat_received), with provenance fields
    (delivery_mode, platform_ts, history_sync_id) stamped by the
    adapter's sync state machine;
  * one ``conversation_sync`` PEVR cycle per completed sync session,
    via the adapter's sync_emitter (LedgerWriter.emit_conversation_sync).

The integration sketch verifies the wire end-to-end: log line →
dispatch → adapter → InfraEvent → writer → ledger entries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)
from wormbase_channel_adapters.types import SecretBundle

from wormbase_channel_adapter.service import WhatsAppLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


@pytest.fixture
def writer(company_id: UUID) -> LedgerWriter:
    return LedgerWriter(InMemoryLedger(), company_id)


def _baileys_msg(
    *,
    msg_id: str,
    jid: str = "5511999999999@s.whatsapp.net",
    body: str = "hello",
    ts_unix: int | None = None,
) -> dict:
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


def _executes(rows: list[dict], tool: str) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


@pytest.mark.asyncio
async def test_admit_writes_chat_received_with_push_provenance(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """A LIVE-state admit writes one chat_received with delivery_mode=push."""
    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    # Drive the state machine straight to LIVE without messages.
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()
    assert adapter.state == _WhatsAppSyncState.LIVE

    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    jid = "5511999999999@s.whatsapp.net"
    adapter.inject_message(jid, _baileys_msg(msg_id="M1", jid=jid))

    await capture.on_channel_admit(jid)

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    # +1 conversation_sync from on_history_set + 1 chat_received here.
    assert len(chat_executes) == 1
    args = chat_executes[0]["payload"]["args"]
    assert args["channel_id"] == jid
    assert args["message_id"] == "M1"
    assert args["text"] == "hello"
    assert args["delivery_mode"] == "push"
    assert args["history_sync_id"] is None
    assert args["platform_ts"] is not None


@pytest.mark.asyncio
async def test_admit_during_sync_stamps_history_sync(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """A SYNC_IN_PROGRESS admit writes chat_received with history_sync_id."""
    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_id="install-1",
        sync_quiet_window_s=60.0,  # large — we drive completion manually
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    await adapter.on_connection_open(trigger="reconnect")

    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    jid = "5511999999999@s.whatsapp.net"
    adapter.inject_message(
        jid, _baileys_msg(msg_id="M1", jid=jid, body="historical"),
    )

    await capture.on_channel_admit(jid)

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_executes) == 1
    args = chat_executes[0]["payload"]["args"]
    assert args["delivery_mode"] == "history_sync"
    assert args["history_sync_id"] is not None
    # And the sync_id matches the active sync.
    assert adapter.active_sync is not None
    assert args["history_sync_id"] == str(adapter.active_sync.sync_id)
    await adapter.shutdown()


@pytest.mark.asyncio
async def test_history_set_writes_conversation_sync_entry(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Completing a sync writes a conversation_sync ledger entry via PEVR."""
    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    await adapter.on_connection_open(trigger="reconnect")

    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    jid = "5511999999999@s.whatsapp.net"
    for i in range(3):
        adapter.inject_message(
            jid, _baileys_msg(msg_id=f"M{i}", jid=jid),
        )
        await capture.on_channel_admit(jid)

    # Complete the sync session.
    await adapter.on_history_set()
    rows = await writer._ledger.fetch(company_id)

    # 3 chat_received PEVR cycles + 1 conversation_sync PEVR cycle = 16 entries.
    sync_executes = _executes(rows, "channel_adapter.emit_conversation_sync")
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(sync_executes) == 1
    assert len(chat_executes) == 3

    sync_args = sync_executes[0]["payload"]["args"]
    assert sync_args["platform"] == "whatsapp"
    assert sync_args["install_id"] == "install-1"
    assert sync_args["channels"] == [jid]
    assert sync_args["message_count"] == 3
    assert sync_args["status"] == "completed"
    assert sync_args["trigger"] == "reconnect"
    # All chat_received entries reference the conversation_sync's ref.
    sync_id = sync_args["sync_id"]
    for ce in chat_executes:
        assert ce["payload"]["args"]["history_sync_id"] == sync_id


@pytest.mark.asyncio
async def test_admit_no_op_when_adapter_returns_none(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """No InfraEvent → no ledger write (graceful drop)."""
    adapter = WhatsAppChannelAdapter()
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )
    # Drive to LIVE.
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()

    # No injected message — fetch_latest_and_normalize returns None.
    await capture.on_channel_admit("5511999999999@s.whatsapp.net")

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert chat_executes == []


@pytest.mark.asyncio
async def test_admit_dedups_same_message_id(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """Same (channel, message_id) seen twice → second is dedup'd by writer."""
    adapter = WhatsAppChannelAdapter()
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()

    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    jid = "5511999999999@s.whatsapp.net"
    # Inject the same message twice (production: replay flood).
    adapter.inject_message(jid, _baileys_msg(msg_id="M-DUP", jid=jid))
    await capture.on_channel_admit(jid)
    adapter.inject_message(jid, _baileys_msg(msg_id="M-DUP", jid=jid))
    await capture.on_channel_admit(jid)

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    # Writer dedup absorbs the duplicate.
    assert len(chat_executes) == 1


@pytest.mark.asyncio
async def test_admit_drops_event_with_no_message_id(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """An InfraEvent with no platform_message_id is dropped (defensive)."""
    adapter = WhatsAppChannelAdapter()
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-1"})
    )
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()

    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    jid = "5511999999999@s.whatsapp.net"
    # Message without a key.id.
    bad = {
        "key": {"remoteJid": jid},
        "message": {"conversation": "no id"},
        "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    adapter.inject_message(jid, bad)
    await capture.on_channel_admit(jid)

    rows = await writer._ledger.fetch(company_id)
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert chat_executes == []


@pytest.mark.asyncio
async def test_writer_emit_conversation_sync_is_callable_as_sync_emitter(
    writer: LedgerWriter, company_id: UUID,
) -> None:
    """The wire contract: writer.emit_conversation_sync matches the
    sync_emitter signature WhatsAppChannelAdapter expects.

    Pin the contract here so we'd catch a signature drift on either
    side. The adapter calls the emitter with kwargs — this test just
    asserts the call shape works.
    """
    from uuid import uuid4

    sync_id = uuid4()
    started = datetime.now(timezone.utc)
    completed = datetime.now(timezone.utc)
    result = await writer.emit_conversation_sync(
        sync_id=sync_id,
        platform="whatsapp",
        install_id="install-1",
        channels=["5511999999999@s.whatsapp.net"],
        trigger="initial_connect",
        started_at=started,
        completed_at=completed,
        message_count=0,
        earliest_ts=None,
        latest_ts=None,
        status="completed",
    )
    assert result is not None
    rows = await writer._ledger.fetch(company_id)
    sync_executes = _executes(rows, "channel_adapter.emit_conversation_sync")
    assert len(sync_executes) == 1


# --------------------------------------------------------------------------
# Wire-completeness: the dispatch table at platform_admit_handlers["whatsapp"]
# is populated only when whatsapp_account_id is configured.
# --------------------------------------------------------------------------


def test_run_service_signature_accepts_whatsapp_account_id() -> None:
    """The run_service kwarg surface includes whatsapp_account_id.

    Pin the contract: __main__/cli passes WHATSAPP_ACCOUNT_ID through;
    if this kwarg disappears or is renamed, the wire breaks silently.
    """
    import inspect

    from wormbase_channel_adapter.service import run_service

    sig = inspect.signature(run_service)
    assert "whatsapp_account_id" in sig.parameters
    # Default is None — Slack-only deployments stay byte-identical.
    assert sig.parameters["whatsapp_account_id"].default is None
