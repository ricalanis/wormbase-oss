"""Tests for WhatsApp reconnect-storm resilience (Wave E1, 2026-05-06).

Verifies that the adapter's sync state machine + a writer-level
``(channel_id, message_id)`` LRU dedup composes correctly under realistic
Baileys reconnect-replay behavior:

* Two-cycle reconnect storm — connection_open → 50 history messages →
  drop → connection_open → 10 more history messages. Two distinct
  ``conversation_sync`` entries with distinct sync_ids; 60 unique
  ``chat_received`` rows; each chat_received's ``history_sync_id``
  matches its session's sync_id.
* Mid-sync interruption — drop BEFORE the quiet window writes the first
  ``conversation_sync`` with ``status="interrupted"`` and the
  accumulated message_count, then a fresh sync completes cleanly.
* Repeat-message dedup — Baileys reconnect-replay can re-deliver the
  same Baileys ``key.id`` twice; the writer's
  ``(channel_id, message_id)`` LRU dedup absorbs the second arrival as
  a no-op while the adapter still stamps a fresh InfraEvent (the
  adapter is liberal; the writer is strict — substrate-level
  idempotency).
* State machine returns to LIVE after sync — once the quiet window
  fires, subsequent live messages stamp ``delivery_mode="push"``,
  ``history_sync_id=None``.
* Multi-channel during sync — messages interleaved across 3 jids
  accumulate into a single ``conversation_sync.channels`` list per the
  per-reconnect granularity locked in the plan.

Determinism: the adapter is constructed with a small
``sync_quiet_window_s`` (50ms) so the asyncio quiet-window task fires
quickly; tests await the timer with a slightly longer ``asyncio.sleep``.
A fake clock is injected so adapter timestamps are deterministic
without monkeypatching ``datetime.now``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)


# Quiet-window short enough to keep the file under 5s wall-clock.
# Tests sleep slightly longer than this to let the timer fire.
_QUIET_WINDOW_S = 0.05
_TIMER_SETTLE_S = 0.15


# --------------------------------------------------------------------------
# Test stand-ins: emitter for conversation_sync, writer for chat_received
# --------------------------------------------------------------------------


class _CaptureSyncEmitter:
    """Test stand-in for ``LedgerWriter.emit_conversation_sync``.

    Records every call's kwargs in arrival order. Each call is one full
    PEVR cycle worth of conversation_sync metadata.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _MockChatReceivedWriter:
    """Test stand-in for ``LedgerWriter._emit_chat_received``.

    Mirrors the real writer's ``(channel_id, message_id)`` LRU dedup
    contract from
    ``apps/channel-adapter/src/wormbase_channel_adapter/writer.py``
    (lines 86-94 + 120-125): a second arrival of the same key returns
    None and writes nothing.

    For E1 we don't exercise the full Pydantic payload validation — we
    only need the dedup-and-record contract since the assertion
    surface is "unique chat_received rows + provenance integrity".
    """

    LRU_MAX = 1024

    def __init__(self) -> None:
        # Insertion-ordered for LRU eviction.
        self._seen: dict[tuple[str, str], None] = {}
        # Captured emissions (post-dedup).
        self.emissions: list[dict[str, Any]] = []

    async def emit_chat_received(
        self,
        *,
        channel_id: str,
        message_id: str,
        delivery_mode: str,
        platform_ts: datetime | None,
        history_sync_id: str | None,
        text: str,
    ) -> bool:
        """Returns True if the row was written, False if dedup'd."""
        key = (channel_id, message_id)
        if key in self._seen:
            return False
        if len(self._seen) >= self.LRU_MAX:
            self._seen.pop(next(iter(self._seen)))
        self._seen[key] = None
        self.emissions.append(
            {
                "channel_id": channel_id,
                "message_id": message_id,
                "delivery_mode": delivery_mode,
                "platform_ts": platform_ts,
                "history_sync_id": history_sync_id,
                "text": text,
            }
        )
        return True


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _baileys(
    *,
    msg_id: str,
    jid: str,
    body: str = "x",
    ts_unix: int | None = None,
) -> dict[str, Any]:
    """Build a minimal Baileys message envelope.

    Mirrors the helper in ``test_whatsapp_sync_state_machine.py`` —
    duplicated locally so this file is self-contained per the plan's
    "build minimal harness inline (don't over-share)" guidance.
    """
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


class _FakeClock:
    """Deterministic clock for the adapter.

    Each ``__call__`` returns the current ``now`` and advances by a
    configurable tick (default 1ms) so successive emissions get
    monotonically-increasing timestamps without coupling to
    wall-clock.
    """

    def __init__(
        self,
        *,
        start: datetime | None = None,
        tick: timedelta = timedelta(milliseconds=1),
    ) -> None:
        self.now = start or datetime(
            2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc,
        )
        self.tick = tick

    def __call__(self) -> datetime:
        cur = self.now
        self.now = self.now + self.tick
        return cur


async def _drive_through_writer(
    adapter: WhatsAppChannelAdapter,
    writer: _MockChatReceivedWriter,
    handle: Any,
    *,
    channel_id: str,
    msg_id: str,
    body: str = "x",
    ts_unix: int | None = None,
) -> None:
    """Inject + fetch + (mock-)write one message through the full stack.

    Models what ``apps/channel-adapter/service.py::on_channel_admit``
    does for WhatsApp: ``inject_message`` → ``fetch_latest_and_normalize``
    → ``LedgerWriter.emit(ChatReceivedEvent)``. Here the writer is the
    in-test mock that mirrors the real LRU contract.
    """
    adapter.inject_message(
        channel_id, _baileys(msg_id=msg_id, jid=channel_id, body=body, ts_unix=ts_unix),
    )
    event = await adapter.fetch_latest_and_normalize(handle, channel_id)
    if event is None:
        return
    await writer.emit_chat_received(
        channel_id=channel_id,
        message_id=event.platform_message_id or "",
        delivery_mode=event.delivery_mode or "push",
        platform_ts=event.platform_ts,
        history_sync_id=event.history_sync_id,
        text=event.text,
    )


# --------------------------------------------------------------------------
# 1. Two-cycle reconnect storm
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_cycle_reconnect_storm_writes_two_distinct_syncs() -> None:
    """50 history messages → drop → 10 more history messages.

    Asserts:
      * Two distinct conversation_sync entries with different sync_ids
      * 60 unique chat_received emissions (no double-writes)
      * Each chat_received's history_sync_id matches the parent
        conversation_sync's sync_id (string match)
      * Both syncs have status="completed"
    """
    sync_emitter = _CaptureSyncEmitter()
    writer = _MockChatReceivedWriter()
    clock = _FakeClock()
    adapter = WhatsAppChannelAdapter(
        sync_emitter=sync_emitter,
        sync_quiet_window_s=_QUIET_WINDOW_S,
        clock=clock,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"

    # ----- First cycle: 50 historical messages -----
    await adapter.on_connection_open(trigger="initial_connect")
    assert adapter.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    for i in range(50):
        await _drive_through_writer(
            adapter, writer, handle,
            channel_id=jid, msg_id=f"S1-M{i}",
        )
    # Quiet-window fires → SYNC_IN_PROGRESS → LIVE; conversation_sync
    # written.
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter.state == _WhatsAppSyncState.LIVE
    assert len(sync_emitter.calls) == 1
    first_sync = sync_emitter.calls[0]
    assert first_sync["status"] == "completed"
    assert first_sync["message_count"] == 50
    sync_id_1 = first_sync["sync_id"]
    assert isinstance(sync_id_1, UUID)

    # ----- Drop -----
    await adapter.on_connection_drop()
    assert adapter.state == _WhatsAppSyncState.IDLE

    # ----- Second cycle: 10 more historical messages -----
    await adapter.on_connection_open(trigger="reconnect")
    assert adapter.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    for i in range(10):
        await _drive_through_writer(
            adapter, writer, handle,
            channel_id=jid, msg_id=f"S2-M{i}",
        )
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter.state == _WhatsAppSyncState.LIVE
    assert len(sync_emitter.calls) == 2
    second_sync = sync_emitter.calls[1]
    assert second_sync["status"] == "completed"
    assert second_sync["message_count"] == 10
    sync_id_2 = second_sync["sync_id"]
    assert isinstance(sync_id_2, UUID)

    # ----- Sync ids are distinct -----
    assert sync_id_1 != sync_id_2

    # ----- All 60 chat_received emissions are unique -----
    assert len(writer.emissions) == 60
    keys = {(e["channel_id"], e["message_id"]) for e in writer.emissions}
    assert len(keys) == 60

    # ----- Provenance integrity: each emission's history_sync_id matches its session's sync_id -----
    sync_id_1_str = str(sync_id_1)
    sync_id_2_str = str(sync_id_2)
    first_50 = writer.emissions[:50]
    next_10 = writer.emissions[50:]
    for e in first_50:
        assert e["delivery_mode"] == "history_sync"
        assert e["history_sync_id"] == sync_id_1_str
    for e in next_10:
        assert e["delivery_mode"] == "history_sync"
        assert e["history_sync_id"] == sync_id_2_str

    await adapter.shutdown()


# --------------------------------------------------------------------------
# 2. Reconnect mid-sync writes status="interrupted"
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_mid_sync_writes_interrupted_then_completed() -> None:
    """Drop BEFORE the quiet window → status="interrupted".

    Then a fresh connection_open → 20 messages → quiet → completed.
    Asserts:
      * First conversation_sync has status="interrupted", message_count=30
      * Second conversation_sync has status="completed", message_count=20
      * Sync ids are distinct
      * No chat_received double-writes (50 unique emissions)
    """
    sync_emitter = _CaptureSyncEmitter()
    writer = _MockChatReceivedWriter()
    clock = _FakeClock()
    adapter = WhatsAppChannelAdapter(
        sync_emitter=sync_emitter,
        # Use a generous window so only on_connection_drop closes
        # session 1 — the quiet-window timer must NOT fire before the
        # drop, otherwise the test races.
        sync_quiet_window_s=60.0,
        clock=clock,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"

    # ----- First cycle: 30 history messages, then drop mid-sync -----
    await adapter.on_connection_open(trigger="initial_connect")
    for i in range(30):
        await _drive_through_writer(
            adapter, writer, handle,
            channel_id=jid, msg_id=f"S1-M{i}",
        )
    assert adapter.state == _WhatsAppSyncState.SYNC_IN_PROGRESS

    await adapter.on_connection_drop()
    assert adapter.state == _WhatsAppSyncState.IDLE
    assert len(sync_emitter.calls) == 1
    first_sync = sync_emitter.calls[0]
    assert first_sync["status"] == "interrupted"
    assert first_sync["message_count"] == 30
    sync_id_1 = first_sync["sync_id"]

    # Switch to a tight quiet window for the second cycle so the test
    # finishes promptly.
    adapter._sync_quiet_window_s = _QUIET_WINDOW_S  # type: ignore[attr-defined]

    # ----- Second cycle: 20 more history messages → completed -----
    await adapter.on_connection_open(trigger="reconnect")
    for i in range(20):
        await _drive_through_writer(
            adapter, writer, handle,
            channel_id=jid, msg_id=f"S2-M{i}",
        )
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter.state == _WhatsAppSyncState.LIVE
    assert len(sync_emitter.calls) == 2
    second_sync = sync_emitter.calls[1]
    assert second_sync["status"] == "completed"
    assert second_sync["message_count"] == 20
    sync_id_2 = second_sync["sync_id"]

    # ----- Sync ids are distinct -----
    assert sync_id_1 != sync_id_2

    # ----- All 50 chat_received emissions are unique -----
    assert len(writer.emissions) == 50
    keys = {(e["channel_id"], e["message_id"]) for e in writer.emissions}
    assert len(keys) == 50

    await adapter.shutdown()


# --------------------------------------------------------------------------
# 3. Repeat-message dedup via writer LRU
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_message_id_is_writer_dedup_no_op() -> None:
    """Same Baileys message_id injected twice → only one chat_received row.

    Models the Baileys reconnect-replay quirk where a single message_id
    can flow twice across two reconnect cycles. The adapter is liberal
    (it stamps a fresh InfraEvent each time), but the writer's
    ``(channel_id, message_id)`` LRU dedup absorbs the second arrival.

    Asserts:
      * The second emit_chat_received call returns False (dedup'd)
      * Only one entry exists in writer.emissions
    """
    sync_emitter = _CaptureSyncEmitter()
    writer = _MockChatReceivedWriter()
    clock = _FakeClock()
    adapter = WhatsAppChannelAdapter(
        sync_emitter=sync_emitter,
        sync_quiet_window_s=60.0,  # large; we don't want the timer firing
        clock=clock,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"

    await adapter.on_connection_open(trigger="initial_connect")

    # First injection: fresh write.
    msg_id = "REPLAY-M1"
    adapter.inject_message(
        jid, _baileys(msg_id=msg_id, jid=jid, body="hello"),
    )
    event_1 = await adapter.fetch_latest_and_normalize(handle, jid)
    assert event_1 is not None
    written_1 = await writer.emit_chat_received(
        channel_id=jid,
        message_id=event_1.platform_message_id or "",
        delivery_mode=event_1.delivery_mode or "push",
        platform_ts=event_1.platform_ts,
        history_sync_id=event_1.history_sync_id,
        text=event_1.text,
    )
    assert written_1 is True

    # Second injection of the SAME message_id: adapter still produces
    # an InfraEvent, but the writer dedup returns False.
    adapter.inject_message(
        jid, _baileys(msg_id=msg_id, jid=jid, body="hello"),
    )
    event_2 = await adapter.fetch_latest_and_normalize(handle, jid)
    assert event_2 is not None
    assert event_2.platform_message_id == msg_id
    written_2 = await writer.emit_chat_received(
        channel_id=jid,
        message_id=event_2.platform_message_id or "",
        delivery_mode=event_2.delivery_mode or "push",
        platform_ts=event_2.platform_ts,
        history_sync_id=event_2.history_sync_id,
        text=event_2.text,
    )
    assert written_2 is False

    # Only one chat_received row landed.
    assert len(writer.emissions) == 1
    assert writer.emissions[0]["message_id"] == msg_id

    await adapter.shutdown()


# --------------------------------------------------------------------------
# 4. State machine returns to LIVE; subsequent message stamps push
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_returns_to_live_and_subsequent_message_is_push() -> None:
    """After 5 messages + quiet window, state is LIVE and next message is push.

    Asserts:
      * State is LIVE after the quiet-window fires
      * The next message's chat_received row has
        delivery_mode="push", history_sync_id=None
    """
    sync_emitter = _CaptureSyncEmitter()
    writer = _MockChatReceivedWriter()
    clock = _FakeClock()
    adapter = WhatsAppChannelAdapter(
        sync_emitter=sync_emitter,
        sync_quiet_window_s=_QUIET_WINDOW_S,
        clock=clock,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )
    jid = "5511999999999@s.whatsapp.net"

    # 5 history messages, then quiet → LIVE
    await adapter.on_connection_open(trigger="initial_connect")
    for i in range(5):
        await _drive_through_writer(
            adapter, writer, handle,
            channel_id=jid, msg_id=f"H-{i}",
        )
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter.state == _WhatsAppSyncState.LIVE
    assert len(sync_emitter.calls) == 1

    # One more (live, fresh) message — adapter stamps push.
    fresh_ts = int(clock.now.timestamp())
    await _drive_through_writer(
        adapter, writer, handle,
        channel_id=jid, msg_id="LIVE-1",
        ts_unix=fresh_ts,
    )

    # State stays LIVE.
    assert adapter.state == _WhatsAppSyncState.LIVE

    # The most-recent chat_received emission is the LIVE-1 row.
    assert len(writer.emissions) == 6
    last = writer.emissions[-1]
    assert last["message_id"] == "LIVE-1"
    assert last["delivery_mode"] == "push"
    assert last["history_sync_id"] is None

    await adapter.shutdown()


# --------------------------------------------------------------------------
# 5. Multi-channel during sync: channels list captures all jids
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_channel_during_sync_accumulates_all_jids() -> None:
    """Messages interleaved across 3 jids accumulate into one sync.

    Per the plan-locked decision: per-reconnect granularity, with a
    ``channels`` list field on the conversation_sync entry that
    contains the sorted set of jids seen during the session.
    """
    sync_emitter = _CaptureSyncEmitter()
    writer = _MockChatReceivedWriter()
    clock = _FakeClock()
    adapter = WhatsAppChannelAdapter(
        sync_emitter=sync_emitter,
        sync_quiet_window_s=_QUIET_WINDOW_S,
        clock=clock,
        install_id="install-1",
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "wa-1"})
    )

    jid_a = "5511111111111@s.whatsapp.net"
    jid_b = "5522222222222@s.whatsapp.net"
    jid_c = "120363012345678901@g.us"  # group jid

    await adapter.on_connection_open(trigger="initial_connect")

    # Interleave 6 messages across 3 jids: a, b, c, a, b, c
    interleaved = [
        (jid_a, "A-1"),
        (jid_b, "B-1"),
        (jid_c, "C-1"),
        (jid_a, "A-2"),
        (jid_b, "B-2"),
        (jid_c, "C-2"),
    ]
    for jid, msg_id in interleaved:
        await _drive_through_writer(
            adapter, writer, handle, channel_id=jid, msg_id=msg_id,
        )
    await asyncio.sleep(_TIMER_SETTLE_S)
    assert adapter.state == _WhatsAppSyncState.LIVE
    assert len(sync_emitter.calls) == 1

    call = sync_emitter.calls[0]
    assert call["status"] == "completed"
    assert call["message_count"] == 6
    # channels is sorted (per LedgerWriter.emit_conversation_sync wiring)
    assert call["channels"] == sorted([jid_a, jid_b, jid_c])
    assert set(call["channels"]) == {jid_a, jid_b, jid_c}

    # All 6 chat_received emissions are unique and stamp the same sync_id.
    assert len(writer.emissions) == 6
    sync_id_str = str(call["sync_id"])
    for e in writer.emissions:
        assert e["delivery_mode"] == "history_sync"
        assert e["history_sync_id"] == sync_id_str

    await adapter.shutdown()
