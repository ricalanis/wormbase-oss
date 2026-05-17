"""End-to-end pin for the WhatsApp provenance + lineage architecture.

Phase 5 of `docs/superpowers/plans/2026-05-05-whatsapp-and-conversation-provenance.md`.
Architecture spec: `docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md`.

Exercises the **full production chain** in one test, with no mocks of
the substrate:

  WhatsAppChannelAdapter.inject_message
       ├─→ adapter._classify_message (state machine)
       ├─→ adapter._normalize_message (InfraEvent w/ provenance)
       ├─→ ChatReceivedEvent
       ├─→ LedgerWriter._emit_chat_received
       │      → InMemoryLedger PEVR cycle
       └─→ adapter._complete_sync
              → LedgerWriter.emit_conversation_sync
                  → InMemoryLedger PEVR cycle

Then we re-read the ledger and assert:

  1. One conversation_sync entry, status=completed, message_count=50,
     channels=[<jid>], earliest/latest_ts straddle the injected range.
  2. Fifty chat_received entries, each with delivery_mode=history_sync
     and history_sync_id == str(sync_id).
  3. A 51st live message stamped delivery_mode=push, history_sync_id=None.
  4. F1/F2/F4 reactivities (LiveOnly-gated) do not fire on any of the 50
     history entries; F1 fires on the live entry.
  5. F3 InterjectionBudgetReactivity is independent of delivery_mode
     (tested with a synthetic clarify_asked entry).
  6. Replay-by-sync_id query returns exactly the 50 history messages.

This test is the architectural contract; if it breaks, the provenance
substrate has regressed.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from wormbase_channel_adapter.service import WhatsAppLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter
from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)
from wormbase_chat_presence.reactivities import (
    ChatReceivedReactivity,
    InterjectionBudgetReactivity,
    MentionResponseReactivity,
    SourceMentionedReactivity,
)
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import ReactivityContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _baileys(
    *,
    msg_id: str,
    jid: str,
    body: str = "x",
    ts_unix: int,
) -> dict[str, Any]:
    """A Baileys-shaped inbound message dict."""
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


def _executes(rows: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


def _ctx(company_id: Any, ledger: Any) -> ReactivityContext:
    return ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=None,
        now=lambda: datetime.now(UTC),
        extras={"reactivity_id": "test"},
    )


# ---------------------------------------------------------------------------
# The big one — full chain pin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_provenance_full_chain_e2e() -> None:
    """One test, full chain, all provenance + lineage assertions.

    Production-shaped: real WhatsAppChannelAdapter (not a mock), real
    LedgerWriter against InMemoryLedger, real WhatsAppLogCapture wiring,
    real chat-presence Reactivities checking their conditions.
    """
    company_id = tenant_to_company_uuid("baseworm")
    ledger = InMemoryLedger()
    writer = LedgerWriter(ledger, company_id)

    # ------------------------------------------------------------------
    # 1. Build the WhatsApp adapter wired to the real LedgerWriter.
    #    Use a sync_quiet_window the test can blow past quickly without
    #    sleeping for real seconds.
    # ------------------------------------------------------------------
    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_id="install-e2e",
        sync_quiet_window_s=0.05,  # 50ms — drives the timer fast
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-e2e"})
    )
    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )
    assert adapter.state == _WhatsAppSyncState.IDLE

    # ------------------------------------------------------------------
    # 2. Drive IDLE → SYNC_IN_PROGRESS via simulated connection_open.
    # ------------------------------------------------------------------
    await adapter.on_connection_open(trigger="reconnect")
    assert adapter.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    assert adapter.active_sync is not None
    sync_id = adapter.active_sync.sync_id

    # ------------------------------------------------------------------
    # 3. Inject 50 historical messages with platform_ts five minutes in
    #    the past — well outside the LiveOnly freshness window.
    # ------------------------------------------------------------------
    jid = "5511999999999@s.whatsapp.net"
    now = datetime.now(UTC)
    history_base = now - timedelta(minutes=5)

    for i in range(50):
        # Each historical message is 2 seconds apart so earliest/latest
        # are unambiguous. All > freshness_window past → LiveOnly blocks.
        msg_ts = history_base + timedelta(seconds=2 * i)
        msg = _baileys(
            msg_id=f"H{i:03d}",
            jid=jid,
            body=f"history message {i}",
            ts_unix=int(msg_ts.timestamp()),
        )
        adapter.inject_message(jid, msg)
        await capture.on_channel_admit(jid)

    # State machine is still SYNC_IN_PROGRESS — quiet timer hasn't fired.
    assert adapter.state == _WhatsAppSyncState.SYNC_IN_PROGRESS
    assert adapter.active_sync is not None
    assert adapter.active_sync.message_count == 50

    # ------------------------------------------------------------------
    # 4. Drive SYNC_IN_PROGRESS → LIVE by waiting past the quiet window.
    #    The asyncio task fires _complete_sync, which writes the
    #    conversation_sync PEVR cycle and flips state.
    # ------------------------------------------------------------------
    # Sleep slightly longer than sync_quiet_window_s; cancel margin for
    # OS scheduler jitter.
    await asyncio.sleep(0.3)

    assert adapter.state == _WhatsAppSyncState.LIVE
    assert adapter.active_sync is None  # cleared on completion

    # ------------------------------------------------------------------
    # 5. Assert: one conversation_sync entry, status=completed.
    # ------------------------------------------------------------------
    rows = await ledger.fetch(company_id)
    sync_executes = _executes(rows, "channel_adapter.emit_conversation_sync")
    assert len(sync_executes) == 1, (
        f"expected exactly one conversation_sync entry, got {len(sync_executes)}"
    )
    sync_args = sync_executes[0]["payload"]["args"]
    assert sync_args["sync_id"] == str(sync_id)
    assert sync_args["platform"] == "whatsapp"
    assert sync_args["install_id"] == "install-e2e"
    assert sync_args["status"] == "completed"
    assert sync_args["trigger"] == "reconnect"
    assert sync_args["message_count"] == 50
    assert sync_args["channels"] == [jid]
    # started_at + completed_at populated.
    assert sync_args["started_at"] is not None
    assert sync_args["completed_at"] is not None
    # earliest/latest reflect the injected 5-minute → ~3-minutes-ago window.
    assert sync_args["earliest_ts"] is not None
    assert sync_args["latest_ts"] is not None
    earliest = datetime.fromisoformat(
        str(sync_args["earliest_ts"]).replace("Z", "+00:00")
    )
    latest = datetime.fromisoformat(
        str(sync_args["latest_ts"]).replace("Z", "+00:00")
    )
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=UTC)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    assert earliest < latest
    assert latest - earliest == timedelta(seconds=2 * 49)

    # ------------------------------------------------------------------
    # 6. Assert: 50 chat_received entries, all delivery_mode=history_sync,
    #    all sharing the same history_sync_id == str(sync_id).
    # ------------------------------------------------------------------
    chat_executes = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_executes) == 50, (
        f"expected 50 chat_received entries from history, got {len(chat_executes)}"
    )
    for r in chat_executes:
        args = r["payload"]["args"]
        assert args["delivery_mode"] == "history_sync", (
            f"history message stamped non-history mode: {args['delivery_mode']}"
        )
        assert args["history_sync_id"] == str(sync_id), (
            f"history message has wrong history_sync_id: {args['history_sync_id']}"
        )
        assert args["channel_id"] == jid

    # ------------------------------------------------------------------
    # 7. Inject a 51st live message (platform_ts = now-2s).
    # ------------------------------------------------------------------
    live_ts = datetime.now(UTC) - timedelta(seconds=2)
    live_msg = _baileys(
        msg_id="L001",
        jid=jid,
        body="live message",
        ts_unix=int(live_ts.timestamp()),
    )
    adapter.inject_message(jid, live_msg)
    await capture.on_channel_admit(jid)

    rows_after_live = await ledger.fetch(company_id)
    chat_executes_all = _executes(
        rows_after_live, "channel_adapter.emit_chat_received"
    )
    assert len(chat_executes_all) == 51

    live_entry = chat_executes_all[-1]
    live_args = live_entry["payload"]["args"]
    assert live_args["delivery_mode"] == "push", (
        f"live message stamped non-push mode: {live_args['delivery_mode']}"
    )
    assert live_args["history_sync_id"] is None
    assert live_args["channel_id"] == jid

    # ------------------------------------------------------------------
    # 8. Drive a chat-presence reactivity round.
    #    Build F1/F2/F4 (gated by LiveOnly) and F3 (always-allow).
    #    Assert F1/F2/F4 BLOCK on every history entry.
    #    Assert F1 ALLOWS the live entry.
    # ------------------------------------------------------------------
    f1 = ChatReceivedReactivity()
    f2 = MentionResponseReactivity(handle="@worm")
    f4 = SourceMentionedReactivity()
    f3 = InterjectionBudgetReactivity()
    ctx = _ctx(company_id, ledger)

    # All 50 history entries must fail F1/F2/F4's condition gate.
    f1_history_fires = 0
    f2_history_fires = 0
    f4_history_fires = 0
    for entry in chat_executes:
        # entry["ts"] is the ledger ingest timestamp; LiveOnly compares
        # this against args.platform_ts. With history_sync delivery_mode,
        # LiveOnly returns False unconditionally.
        if await f1.condition.allows(entry, ctx):
            f1_history_fires += 1
        if await f2.condition.allows(entry, ctx):
            f2_history_fires += 1
        if await f4.condition.allows(entry, ctx):
            f4_history_fires += 1

    assert f1_history_fires == 0, (
        f"F1 condition allowed {f1_history_fires} history entries; "
        "LiveOnly is broken"
    )
    assert f2_history_fires == 0, (
        f"F2 condition allowed {f2_history_fires} history entries"
    )
    assert f4_history_fires == 0, (
        f"F4 condition allowed {f4_history_fires} history entries"
    )

    # The live entry passes F1/F2/F4's condition gate (subject to
    # NotRecentlyFired on F4, which is permissive without a registry).
    assert await f1.condition.allows(live_entry, ctx) is True
    assert await f2.condition.allows(live_entry, ctx) is True
    assert await f4.condition.allows(live_entry, ctx) is True

    # ------------------------------------------------------------------
    # 9. F3 InterjectionBudgetReactivity is observation-only — its
    #    condition is AlwaysAllow regardless of delivery_mode.
    #    Test with a synthetic clarify_asked entry stamped history_sync.
    # ------------------------------------------------------------------
    clarify_now = datetime.now(UTC)
    synthetic_clarify_history = {
        "kind": "execute",
        "ts": clarify_now,
        "payload": {
            "tool": "emit_memory_written",
            "args": {
                "content": "clarify_asked:C_test",
                # Stamp as history_sync; LiveOnly would block, but F3
                # uses AlwaysAllow.
                "delivery_mode": "history_sync",
                "platform_ts": (clarify_now - timedelta(hours=2)).isoformat(),
                "history_sync_id": "synthetic-sync-id",
            },
        },
    }
    assert await f3.condition.allows(synthetic_clarify_history, ctx) is True

    synthetic_clarify_live = {
        "kind": "execute",
        "ts": clarify_now,
        "payload": {
            "tool": "emit_memory_written",
            "args": {
                "content": "clarify_asked:C_test",
                "delivery_mode": "push",
                "platform_ts": (clarify_now - timedelta(seconds=2)).isoformat(),
                "history_sync_id": None,
            },
        },
    }
    assert await f3.condition.allows(synthetic_clarify_live, ctx) is True

    # ------------------------------------------------------------------
    # 10. Replay-by-sync_id query: filter chat_received by
    #     history_sync_id and assert exactly the 50 history messages
    #     come back. This is the architectural-traceability invariant.
    # ------------------------------------------------------------------
    sync_id_str = str(sync_id)
    replayed_messages = [
        r for r in chat_executes_all
        if r["payload"]["args"].get("history_sync_id") == sync_id_str
    ]
    assert len(replayed_messages) == 50

    # And every replayed message has a unique message_id, matching the
    # injected H000..H049 sequence.
    replayed_ids = sorted(
        r["payload"]["args"]["message_id"] for r in replayed_messages
    )
    expected_ids = sorted(f"H{i:03d}" for i in range(50))
    assert replayed_ids == expected_ids

    # The live entry is NOT in the replay-by-sync_id slice.
    assert all(
        r["payload"]["args"]["message_id"] != "L001"
        for r in replayed_messages
    )

    # Cleanup: cancel any lingering quiet-timer task. State machine is
    # already LIVE, so this is a no-op for the timer; harmless.
    await adapter.shutdown()
