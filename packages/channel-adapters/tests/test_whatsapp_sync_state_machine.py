"""Tests for the WhatsApp sync state machine + conversation_sync emission.

State transitions covered:

* IDLE → SYNC_IN_PROGRESS on ``on_connection_open``
* SYNC_IN_PROGRESS → LIVE after the quiet-window timer fires
* SYNC_IN_PROGRESS → LIVE on explicit ``on_history_set``
* SYNC_IN_PROGRESS → IDLE on ``on_connection_drop`` mid-sync (interrupted)
* LIVE → IDLE on ``on_connection_drop``
* IDLE → SYNC_IN_PROGRESS auto-flip when a message arrives without a
  prior connection_open signal (defensive heuristic)

Each completion triggers a write through the injected ``sync_emitter``
callable, capturing the kwargs we'd pass to
:meth:`wormbase_channel_adapter.writer.LedgerWriter.emit_conversation_sync`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _ActiveSync,
    _WhatsAppSyncState,
)


class _CaptureEmitter:
    """Test stand-in for LedgerWriter.emit_conversation_sync.

    Records kwargs of every invocation; supports assertion against the
    final call's bounds + status. The real emitter writes a PEVR cycle
    to the ledger; here we just capture the call.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _baileys(
    *,
    msg_id: str,
    jid: str,
    body: str = "x",
    ts_unix: int | None = None,
) -> dict:
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


# --------------------------------------------------------------------------
# State transitions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_to_sync_in_progress_on_connection_open() -> None:
    a = WhatsAppChannelAdapter()
    assert a.state == _WhatsAppSyncState.IDLE
    await a.on_connection_open(trigger="reconnect")
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    assert a.active_sync is not None
    assert a.active_sync.trigger == "reconnect"
    assert isinstance(a.active_sync.sync_id, UUID)


@pytest.mark.asyncio
async def test_connection_open_is_idempotent_in_sync() -> None:
    """Re-entering SYNC_IN_PROGRESS keeps the same sync_id."""
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="reconnect")
    sync_id_first = a.active_sync.sync_id  # type: ignore[union-attr]
    await a.on_connection_open(trigger="reconnect")
    assert a.active_sync.sync_id == sync_id_first  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_sync_in_progress_to_live_on_quiet_window_timeout() -> None:
    """After the quiet window elapses, the machine flips to LIVE.

    Drives a tiny quiet window so the test is fast and deterministic.
    """
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=0.05,  # 50ms
        install_id="install-1",
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="initial_connect")

    # Surface one message so the timer schedules.
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.delivery_mode == "history_sync"
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    # Wait long enough for the quiet window to fire.
    await asyncio.sleep(0.2)
    assert a.state == _WhatsAppSyncState.LIVE
    # Sync entry was written.
    assert len(emitter.calls) == 1
    call = emitter.calls[0]
    assert call["platform"] == "whatsapp"
    assert call["install_id"] == "install-1"
    assert call["channels"] == [jid]
    assert call["message_count"] == 1
    assert call["status"] == "completed"
    assert call["trigger"] == "initial_connect"
    assert isinstance(call["sync_id"], UUID)
    assert call["earliest_ts"] is not None
    assert call["latest_ts"] is not None


@pytest.mark.asyncio
async def test_sync_in_progress_to_live_on_explicit_history_set() -> None:
    """on_history_set short-circuits the quiet window and flips immediately."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=60.0,  # large — explicit signal must beat it
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    jid = "5511999999999@s.whatsapp.net"
    for i in range(3):
        a.inject_message(jid, _baileys(msg_id=f"M{i}", jid=jid))
        await a.fetch_latest_and_normalize(handle, jid)

    await a.on_history_set()
    assert a.state == _WhatsAppSyncState.LIVE
    assert len(emitter.calls) == 1
    assert emitter.calls[0]["message_count"] == 3
    assert emitter.calls[0]["status"] == "completed"
    await a.shutdown()


@pytest.mark.asyncio
async def test_history_set_is_no_op_when_not_in_sync() -> None:
    """Calling on_history_set in IDLE or LIVE does nothing."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(sync_emitter=emitter)

    # IDLE
    await a.on_history_set()
    assert a.state == _WhatsAppSyncState.IDLE
    assert emitter.calls == []

    # LIVE
    await a.on_connection_open(trigger="reconnect")
    await a.on_history_set()  # → LIVE
    emitter.calls.clear()
    await a.on_history_set()  # already LIVE, no-op
    assert emitter.calls == []


@pytest.mark.asyncio
async def test_connection_drop_mid_sync_writes_interrupted() -> None:
    """Dropping the connection mid-sync writes status=interrupted."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=60.0,
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)

    await a.on_connection_drop()
    assert a.state == _WhatsAppSyncState.IDLE
    assert len(emitter.calls) == 1
    assert emitter.calls[0]["status"] == "interrupted"
    assert emitter.calls[0]["message_count"] == 1


@pytest.mark.asyncio
async def test_live_to_idle_on_connection_drop() -> None:
    """A clean drop in LIVE state goes back to IDLE without a write."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(sync_emitter=emitter)
    await a.on_connection_open(trigger="reconnect")
    await a.on_history_set()  # → LIVE; writes one entry
    assert a.state == _WhatsAppSyncState.LIVE
    emitter.calls.clear()

    await a.on_connection_drop()
    assert a.state == _WhatsAppSyncState.IDLE
    # No additional write — LIVE→IDLE is just a flag flip.
    assert emitter.calls == []


@pytest.mark.asyncio
async def test_message_in_idle_auto_starts_sync() -> None:
    """Defensive: a message arriving in IDLE starts a sync session.

    This handles the case where Baileys delivers history before our
    upstream connection_open dispatcher fires.
    """
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=0.05,
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    assert a.state == _WhatsAppSyncState.IDLE

    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.delivery_mode == "history_sync"
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    # Wait for quiet window.
    await asyncio.sleep(0.2)
    assert a.state == _WhatsAppSyncState.LIVE
    assert len(emitter.calls) == 1
    assert emitter.calls[0]["trigger"] == "reconnect"
    # auto-started sync defaults to "reconnect" trigger


@pytest.mark.asyncio
async def test_multiple_consecutive_syncs_each_get_unique_sync_id() -> None:
    """Drop + reconnect = new sync session with fresh sync_id."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=60.0,
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )

    # First sync.
    await a.on_connection_open(trigger="initial_connect")
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)
    await a.on_history_set()
    sync_id_1 = emitter.calls[0]["sync_id"]

    # Drop and reconnect.
    await a.on_connection_drop()
    assert a.state == _WhatsAppSyncState.IDLE

    # Second sync.
    await a.on_connection_open(trigger="reconnect")
    a.inject_message(jid, _baileys(msg_id="M2", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)
    await a.on_history_set()
    sync_id_2 = emitter.calls[1]["sync_id"]

    assert sync_id_1 != sync_id_2
    assert emitter.calls[0]["trigger"] == "initial_connect"
    assert emitter.calls[1]["trigger"] == "reconnect"


@pytest.mark.asyncio
async def test_messages_in_live_state_do_not_stamp_history_sync() -> None:
    """Once LIVE, every message is delivery_mode=push, history_sync_id=None."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(sync_emitter=emitter)
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    await a.on_history_set()
    assert a.state == _WhatsAppSyncState.LIVE

    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M-live", jid=jid))
    event = await a.fetch_latest_and_normalize(handle, jid)
    assert event is not None
    assert event.delivery_mode == "push"
    assert event.history_sync_id is None


@pytest.mark.asyncio
async def test_quiet_timer_resets_on_new_messages() -> None:
    """Each new message restarts the quiet-window timer.

    Two messages arriving within the window stay SYNC_IN_PROGRESS; only
    when the window elapses with no further activity does the machine
    flip to LIVE.
    """
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=0.10,
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")

    jid = "5511999999999@s.whatsapp.net"

    # Three messages, each within the window — none should trigger
    # completion.
    for i in range(3):
        a.inject_message(jid, _baileys(msg_id=f"M{i}", jid=jid))
        await a.fetch_latest_and_normalize(handle, jid)
        await asyncio.sleep(0.05)  # half the window
    # Still in sync.
    assert a.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    assert emitter.calls == []

    # Wait long enough for the window to fully elapse.
    await asyncio.sleep(0.2)
    assert a.state == _WhatsAppSyncState.LIVE
    assert len(emitter.calls) == 1
    assert emitter.calls[0]["message_count"] == 3


@pytest.mark.asyncio
async def test_active_sync_accumulates_channels_and_bounds() -> None:
    """SYNC_IN_PROGRESS accumulates: channels (set), message_count, ts bounds."""
    emitter = _CaptureEmitter()
    a = WhatsAppChannelAdapter(
        sync_emitter=emitter,
        sync_quiet_window_s=60.0,
    )
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")

    base_ts = int(datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc).timestamp())
    jid_a = "5511111111111@s.whatsapp.net"
    jid_b = "120363012345678901@g.us"

    # Spread messages across timestamps + channels.
    for offset, jid in [
        (0, jid_a),
        (5, jid_a),
        (10, jid_b),
        (3, jid_b),  # earliest in jid_b but not overall
    ]:
        a.inject_message(
            jid, _baileys(msg_id=f"M-{offset}", jid=jid, ts_unix=base_ts + offset),
        )
        await a.fetch_latest_and_normalize(handle, jid)

    assert a.active_sync is not None
    assert a.active_sync.message_count == 4
    assert a.active_sync.channels == {jid_a, jid_b}
    assert a.active_sync.earliest_ts == datetime.fromtimestamp(
        base_ts, tz=timezone.utc,
    )
    assert a.active_sync.latest_ts == datetime.fromtimestamp(
        base_ts + 10, tz=timezone.utc,
    )

    # Complete and check the emitter received the same bounds + sorted
    # channels.
    await a.on_history_set()
    call = emitter.calls[0]
    assert call["message_count"] == 4
    assert call["channels"] == sorted([jid_a, jid_b])
    assert call["earliest_ts"] == datetime.fromtimestamp(
        base_ts, tz=timezone.utc,
    )
    assert call["latest_ts"] == datetime.fromtimestamp(
        base_ts + 10, tz=timezone.utc,
    )


@pytest.mark.asyncio
async def test_no_emitter_logs_but_does_not_raise() -> None:
    """If sync_emitter is None, completion is a no-op write (log only)."""
    a = WhatsAppChannelAdapter(sync_emitter=None)  # explicit
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)
    # on_history_set must not raise even with no emitter.
    await a.on_history_set()
    assert a.state == _WhatsAppSyncState.LIVE


@pytest.mark.asyncio
async def test_emitter_exception_does_not_break_state_machine() -> None:
    """A failing emitter must not leave the machine in an inconsistent state."""

    async def _broken_emitter(**kwargs: Any) -> None:
        raise RuntimeError("ledger write failed")

    a = WhatsAppChannelAdapter(sync_emitter=_broken_emitter)
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)
    # Must not raise.
    await a.on_history_set()
    # State has still flipped to LIVE — broken-emitter is logged, not re-raised.
    assert a.state == _WhatsAppSyncState.LIVE


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_quiet_timer() -> None:
    """Shutdown cancels the quiet-window task cleanly."""
    a = WhatsAppChannelAdapter(sync_quiet_window_s=60.0)
    handle = await a.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    await a.on_connection_open(trigger="reconnect")
    jid = "5511999999999@s.whatsapp.net"
    a.inject_message(jid, _baileys(msg_id="M1", jid=jid))
    await a.fetch_latest_and_normalize(handle, jid)
    # Timer is pending.
    assert a._quiet_timer_task is not None
    await a.shutdown()
    # Timer is cleaned up.
    assert a._quiet_timer_task is None


# --------------------------------------------------------------------------
# Smoke: _ActiveSync dataclass shape
# --------------------------------------------------------------------------


def test_active_sync_dataclass_fields() -> None:
    """_ActiveSync stores the bookkeeping the conversation_sync write needs."""
    from uuid import uuid4

    s = _ActiveSync(
        sync_id=uuid4(),
        trigger="initial_connect",
        started_at=datetime.now(timezone.utc),
    )
    assert s.message_count == 0
    assert s.earliest_ts is None
    assert s.latest_ts is None
    assert s.last_message_at is None
    assert s.channels == set()
