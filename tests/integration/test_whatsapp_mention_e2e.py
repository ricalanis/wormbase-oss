"""End-to-end pin: WhatsApp mention flows from wire to predicate.

Closes the loop on Wave B1's deferred finding (B1 shipped a forward-compat
predicate; the writer was dropping mentioned_jids at the boundary, so the
WhatsApp mention branch evaluated to False on real ledger entries).

The chain:

  WhatsAppChannelAdapter.inject_message
       ├─→ adapter._normalize_message  (extracts mentioned_jids from
       │    payload.message.extendedTextMessage.contextInfo.mentionedJid)
       ├─→ InfraEvent.mentioned_jids populated
       ├─→ WhatsAppLogCapture builds ChatReceivedEvent forwarding the field
       ├─→ LedgerWriter._emit_chat_received threads it into
       │    ChatReceivedPayload.mentioned_jids
       └─→ Ledger entry's execute.args carries ``mentioned_jids: [<jid>, ...]``

Then we re-read the ledger and assert MentionsWorm's WhatsApp branch
matches:

  bot_jid in args.mentioned_jids → predicate True
  bot_jid NOT in args.mentioned_jids → predicate False

This is the architectural-pin that B1's forward-compat code (frontend)
+ B1.1's writer threading (backend) close the production gap together.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from wormbase_channel_adapter.service import WhatsAppLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid
from wormbase_channel_adapter.writer import LedgerWriter
from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter
from wormbase_chat_presence.predicates import MentionsWorm
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.protocol import ReactivityContext


_TENANT = "baseworm"
_BOT_PHONE = "5511888888888"
_BOT_JID = f"{_BOT_PHONE}@s.whatsapp.net"
_USER_JID = "5511999999999@s.whatsapp.net"  # the DM channel + sender
_OTHER_JID = "5511777777777@s.whatsapp.net"


def _baileys_with_mentions(
    *,
    msg_id: str,
    body: str,
    mentioned: list[str],
    ts_unix: int | None = None,
) -> dict[str, Any]:
    """Build a Baileys extendedTextMessage shape with mentions."""
    if ts_unix is None:
        ts_unix = int(datetime.now(UTC).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": _USER_JID},
        "message": {
            "extendedTextMessage": {
                "text": body,
                "contextInfo": {"mentionedJid": mentioned},
            },
        },
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
        extras={"reactivity_id": "test-mention-e2e"},
    )


# ---------------------------------------------------------------------------
# The pin: mention flows wire → ledger → predicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_mention_flows_wire_to_predicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthetic WhatsApp message with mentionedJid containing the bot's
    jid → flows through the production chain → MentionsWorm's WhatsApp
    branch matches on the resulting ledger entry.

    Production-shaped: real WhatsAppChannelAdapter (not a mock), real
    LedgerWriter against InMemoryLedger, real WhatsAppLogCapture wiring,
    real MentionsWorm predicate evaluating against the real entry.
    """
    company_id = tenant_to_company_uuid(_TENANT)
    # Two env conventions in play:
    #  - MentionsWorm predicate scopes by ``company_id`` (UUID, uppercased)
    #  - WhatsAppChannelAdapter / install_emitter scopes by ``tenant_id``
    #    slug (uppercased) — see B1's status note for the resolution.
    # Set both so the production wiring exercises both lookup paths.
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(company_id).upper()}",
        _BOT_PHONE,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}",
        _BOT_PHONE,
    )

    ledger = InMemoryLedger()
    writer = LedgerWriter(ledger, company_id)

    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_emitter=writer.emit_whatsapp_install,
        install_id="install-mention-e2e",
        tenant_id=_TENANT,
        sync_quiet_window_s=0.05,
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-mention-e2e"})
    )
    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )

    # Drive IDLE → SYNC_IN_PROGRESS → LIVE so the mention message lands
    # as a live push (not history-replayed). on_connection_open also
    # exercises the install_emitter path — full production wiring.
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()

    # Inject a message that mentions the bot's jid in contextInfo.
    msg = _baileys_with_mentions(
        msg_id="MENTION-001",
        body=f"hey @{_BOT_PHONE} what's the latest revenue?",
        mentioned=[_BOT_JID, _OTHER_JID],
    )
    adapter.inject_message(_USER_JID, msg)
    await capture.on_channel_admit(_USER_JID)

    # Re-read the ledger and pin the mentioned_jids surface.
    rows = await ledger.fetch(company_id)
    chat_execs = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_execs) == 1
    args = chat_execs[0]["payload"]["args"]
    assert args["channel_id"] == _USER_JID
    assert args["mentioned_jids"] == [_BOT_JID, _OTHER_JID]
    # Provenance: live mention, not history-replayed.
    assert args["delivery_mode"] == "push"
    assert args["history_sync_id"] is None

    # Install emitter fired alongside — pin the install_completed entry.
    install_execs = _executes(rows, "emit_install_completed")
    assert len(install_execs) == 1, (
        "B3.1 wiring regression — install emitter not fired by adapter"
    )
    install_args = install_execs[0]["payload"]["args"]
    assert install_args["bot_user_id"] == _BOT_JID
    assert install_args["platform"] == "whatsapp"

    # Now run the production MentionsWorm predicate against the entry.
    # It should match — the WhatsApp branch reads args.mentioned_jids and
    # finds the bot's jid (resolved from the env we just set).
    predicate = MentionsWorm(handle="@worm")
    ctx = _ctx(company_id, ledger)
    matched = await predicate.match(chat_execs[0], ctx)
    assert matched is True, (
        "MentionsWorm WhatsApp branch did not match — B1.1 writer threading regression"
    )

    # Cleanup.
    await adapter.shutdown()


@pytest.mark.asyncio
async def test_whatsapp_message_without_bot_mention_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A WhatsApp message with mentions but NOT the bot's jid →
    MentionsWorm's WhatsApp branch returns False. Distinguishes "we
    threaded the field through" from "we always match".
    """
    company_id = tenant_to_company_uuid(_TENANT)
    # Two env conventions in play:
    #  - MentionsWorm predicate scopes by ``company_id`` (UUID, uppercased)
    #  - WhatsAppChannelAdapter / install_emitter scopes by ``tenant_id``
    #    slug (uppercased) — see B1's status note for the resolution.
    # Set both so the production wiring exercises both lookup paths.
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(company_id).upper()}",
        _BOT_PHONE,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}",
        _BOT_PHONE,
    )

    ledger = InMemoryLedger()
    writer = LedgerWriter(ledger, company_id)

    adapter = WhatsAppChannelAdapter(
        sync_emitter=writer.emit_conversation_sync,
        install_emitter=writer.emit_whatsapp_install,
        install_id="install-mention-e2e-2",
        tenant_id=_TENANT,
        sync_quiet_window_s=0.05,
    )
    handle = await adapter.authenticate(
        SecretBundle(payload={"account_id": "install-mention-e2e-2"})
    )
    capture = WhatsAppLogCapture(
        adapter=adapter,
        handle=handle,
        writer=writer,
        company_id=company_id,
    )
    await adapter.on_connection_open(trigger="initial_connect")
    await adapter.on_history_set()

    # Mention someone OTHER than the bot.
    msg = _baileys_with_mentions(
        msg_id="MENTION-002",
        body=f"hey @{_OTHER_JID.split('@')[0]} look at this",
        mentioned=[_OTHER_JID],
    )
    adapter.inject_message(_USER_JID, msg)
    await capture.on_channel_admit(_USER_JID)

    rows = await ledger.fetch(company_id)
    chat_execs = _executes(rows, "channel_adapter.emit_chat_received")
    assert len(chat_execs) == 1
    args = chat_execs[0]["payload"]["args"]
    assert args["mentioned_jids"] == [_OTHER_JID]

    predicate = MentionsWorm(handle="@worm")
    ctx = _ctx(company_id, ledger)
    matched = await predicate.match(chat_execs[0], ctx)
    assert matched is False

    await adapter.shutdown()
