"""Tests for WhatsAppChannelAdapter — Protocol conformance + normalization.

Covers the static surface of the adapter (capability set, status badge,
honest-empty list_workspace_members) plus the wire-event normalization
done by ``fetch_latest_and_normalize``. State-machine tests live in
``test_whatsapp_sync_state_machine.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)


# --------------------------------------------------------------------------
# Protocol conformance + capability honesty
# --------------------------------------------------------------------------


def test_whatsapp_implements_channel_adapter() -> None:
    a = WhatsAppChannelAdapter()
    assert isinstance(a, ChannelAdapter)
    assert a.platform == "whatsapp"


def test_whatsapp_capability_set_is_honest() -> None:
    """Capability set: ingest + dm + send (Wave C, 2026-05-06).

    Capability honesty is a hard contract per
    /Users/ricalanis/Dev/agentic_datasci/.claude/CLAUDE.md feedback note
    "Onboarding Production-Only" — adapters declare what works, not
    what they aspire to support. Wave C wired send via the OpenClaw
    CLI subprocess after empirical C1 discovery confirmed there's no
    plain HTTP send route; ``send`` joins the capability set
    accordingly. file_upload remains an explicit non-goal for v1
    (Wave D scope).
    """
    a = WhatsAppChannelAdapter()
    assert "ingest" in a.capability
    assert "dm" in a.capability
    assert "send" in a.capability, (
        "send MUST be wired by Wave C (CLI subprocess via OpenClaw)"
    )
    assert "file_upload" not in a.capability  # explicit non-goal v1


def test_whatsapp_declares_preview_status() -> None:
    a = WhatsAppChannelAdapter()
    assert a.status == "preview"
    assert isinstance(a.status_note, str) and a.status_note


def test_whatsapp_status_note_mentions_baileys_tos() -> None:
    """status_note must surface the ToS caveat — operators see this string."""
    a = WhatsAppChannelAdapter()
    note_lower = a.status_note.lower()
    assert "baileys" in note_lower
    assert "tos" in note_lower or "terms" in note_lower or "unofficial" in note_lower


def test_whatsapp_status_note_mentions_log_grammar_gap() -> None:
    """status_note must surface the empirical-verification gap."""
    a = WhatsAppChannelAdapter()
    assert (
        "empirical" in a.status_note.lower()
        or "unverified" in a.status_note.lower()
    )


def test_whatsapp_status_note_points_to_openclaw_issue() -> None:
    """status_note must reference the upstream tracking issue."""
    a = WhatsAppChannelAdapter()
    assert "73016" in a.status_note


def test_whatsapp_self_registers() -> None:
    from wormbase_channel_adapters.registry import default_registry

    cls = default_registry().get("whatsapp")
    assert cls is WhatsAppChannelAdapter


# --------------------------------------------------------------------------
# authenticate / install
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_requires_account_id() -> None:
    a = WhatsAppChannelAdapter()
    with pytest.raises(ValueError, match="account_id"):
        await a.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_authenticate_returns_handle_with_account_id() -> None:
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={
            "account_id": "baseworm-wa-test",
            "tenant_id": "baseworm",
        })
    )
    assert handle.connector_kind == "whatsapp"
    assert handle.handle_id == "baseworm-wa-test"
    assert handle.extra["account_id"] == "baseworm-wa-test"
    assert handle.extra["tenant_id"] == "baseworm"


@pytest.mark.asyncio
async def test_install_marks_handle_installed() -> None:
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    install = await a.install(handle)
    assert install.platform == "whatsapp"
    assert install.install_id == "wa-1"
    assert install.metadata["transport"] == "baileys"
    # No bot_user_id surface for WhatsApp accounts.
    assert install.bot_user_id is None


# --------------------------------------------------------------------------
# list_workspace_members
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workspace_members_returns_empty_list() -> None:
    """WhatsApp has no global roster — return [] honestly."""
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    members = await a.list_workspace_members(handle)
    assert members == []


# --------------------------------------------------------------------------
# send: Wave C wired the OpenClaw CLI subprocess path. Round-trip + edge
# tests live in test_whatsapp_send.py; the single contract pin here is
# the kill-switch path (WORMBASE_WHATSAPP_SEND_DISABLE) which the ops
# team relies on for emergency disable without a code roll.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_kill_switch_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_WHATSAPP_SEND_DISABLE=1`` hard-disables outbound."""
    monkeypatch.setenv("WORMBASE_WHATSAPP_SEND_DISABLE", "1")
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", "5511888888888")
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    with pytest.raises(NotImplementedError, match="disabled"):
        await a.send(
            handle,
            ChannelRef(
                platform="whatsapp",
                platform_channel_id="5511999999999@s.whatsapp.net",
            ),
            OutMessage(text="hi"),
        )


# --------------------------------------------------------------------------
# fetch_latest_and_normalize: provenance stamping
# --------------------------------------------------------------------------


def _baileys_msg(
    *,
    msg_id: str = "BAEABC",
    remote_jid: str = "5511999999999@s.whatsapp.net",
    participant: str | None = None,
    body: str = "hello",
    ts_unix: int | None = None,
    ext_quote: bool = False,
) -> dict:
    """Build a synthetic Baileys-shape message dict.

    ``participant`` is set for group messages (key.participant carries
    the actual sender's jid); for DMs it stays None and key.remoteJid
    is the peer.
    """
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    if ext_quote:
        message = {"extendedTextMessage": {"text": body}}
    else:
        message = {"conversation": body}
    key: dict = {"id": msg_id, "remoteJid": remote_jid}
    if participant is not None:
        key["participant"] = participant
    return {
        "key": key,
        "message": message,
        "messageTimestamp": ts_unix,
    }


@pytest.mark.asyncio
async def test_fetch_returns_none_when_no_message_available() -> None:
    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    # No injected message — production HTTP route is unverified, so
    # _fetch_message returns None gracefully.
    result = await a.fetch_latest_and_normalize(
        handle, "5511999999999@s.whatsapp.net",
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_dm_marks_source_dm_and_extracts_text() -> None:
    a = WhatsAppChannelAdapter()
    # Skip the sync state machine flips by going straight to LIVE.
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()  # straight to LIVE, no messages
    assert a.state == _WhatsAppSyncState.LIVE

    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys_msg(remote_jid=jid, body="hello world"))

    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.platform == "whatsapp"
    assert event.source == "dm"
    assert event.platform_channel_id == jid
    assert event.platform_user_id == jid  # remoteJid in DMs == sender
    assert event.platform_message_id == "BAEABC"
    assert event.text == "hello world"
    assert event.delivery_mode == "push"
    assert event.history_sync_id is None
    assert event.platform_ts is not None


@pytest.mark.asyncio
async def test_fetch_group_marks_source_channel_and_uses_participant() -> None:
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    group_jid = "120363012345678901@g.us"
    sender_jid = "5511777777777@s.whatsapp.net"
    a.inject_message(
        group_jid,
        _baileys_msg(
            remote_jid=group_jid,
            participant=sender_jid,
            body="group msg",
        ),
    )

    event = await a.fetch_latest_and_normalize(handle, group_jid)
    assert event is not None
    assert event.source == "channel_message"
    assert event.platform_channel_id == group_jid
    # In groups, key.participant is the sender.
    assert event.platform_user_id == sender_jid


@pytest.mark.asyncio
async def test_fetch_extracts_extended_text_message() -> None:
    """Baileys nests text under extendedTextMessage for quotes/forwards."""
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(
        jid,
        _baileys_msg(
            remote_jid=jid,
            body="quoted reply",
            ext_quote=True,
        ),
    )

    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.text == "quoted reply"


@pytest.mark.asyncio
async def test_fetch_handles_missing_text_gracefully() -> None:
    """A media-only message with no text body still produces an event."""
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"
    msg = {
        "key": {"id": "M1", "remoteJid": jid},
        "message": {"imageMessage": {"caption": None}},
        "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    a.inject_message(jid, msg)

    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.text == ""


@pytest.mark.asyncio
async def test_fetch_in_sync_in_progress_stamps_history_sync() -> None:
    """SYNC_IN_PROGRESS + message → delivery_mode=history_sync, sync_id set."""
    a = WhatsAppChannelAdapter(sync_quiet_window_s=60.0)  # large window
    await a.on_connection_open(trigger="reconnect")
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys_msg(remote_jid=jid, body="historical"))

    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.delivery_mode == "history_sync"
    assert event.history_sync_id is not None
    # Same as active_sync.sync_id.
    assert a.active_sync is not None
    assert event.history_sync_id == str(a.active_sync.sync_id)
    # is_live derived predicate is False in history_sync mode.
    assert event.is_live is False
    # Cleanup pending timer task.
    await a.shutdown()


@pytest.mark.asyncio
async def test_fetch_invalid_messageTimestamp_falls_back_to_none() -> None:
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"
    msg = _baileys_msg(remote_jid=jid)
    msg["messageTimestamp"] = "not-a-number"
    a.inject_message(jid, msg)

    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.platform_ts is None


# --------------------------------------------------------------------------
# listen idles forever (Protocol contract; production drives via service.py)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listen_is_async_iterator() -> None:
    """listen() returns an async iterator; we don't drive it.

    Production wiring (apps/channel-adapter/service.py) drives the
    OpenClawLogTailer + dispatch table directly — bypasses listen().
    The adapter still needs to implement it for Protocol conformance.
    """
    import asyncio

    a = WhatsAppChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )

    async def _drain() -> None:
        async for _ in a.listen(handle):
            return  # never reached — listen idles forever

    # Run with a short timeout — listen should still be running when
    # we cancel.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(_drain(), timeout=0.05)
