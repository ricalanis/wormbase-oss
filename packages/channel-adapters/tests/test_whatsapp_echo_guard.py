"""Tests for the WhatsApp echo guard (Wave B4).

Mirrors the structural intent of Slack's bot-id self-echo guard
(``packages/channel-adapters/src/wormbase_channel_adapters/slack.py``
lines 376-384): drop messages where the bot is the sender so its own
outbound doesn't round-trip as a fresh inbound ``chat_received``.

Two detection paths exercised:

1. ``key.fromMe == True`` — Baileys' explicit flag.
2. Sender jid matches the bot's own jid (resolved from env).

The bot phone env is ``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>`` (matches
B1's naming convention) with a global ``WORMBASE_WHATSAPP_BOT_PHONE``
fallback for single-tenant deployments.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wormbase_channel_adapters.types import SecretBundle
from wormbase_channel_adapters.whatsapp import (
    WhatsAppChannelAdapter,
    _WhatsAppSyncState,
)


_BOT_PHONE = "5511888888888"
_BOT_JID = f"{_BOT_PHONE}@s.whatsapp.net"
_TENANT = "baseworm"


def _baileys_msg(
    *,
    msg_id: str = "BAEABC",
    remote_jid: str,
    participant: str | None = None,
    from_me: bool | None = None,
    body: str = "hello",
    ts_unix: int | None = None,
) -> dict:
    """Build a synthetic Baileys-shape message dict.

    ``from_me`` mirrors Baileys' ``key.fromMe`` flag (set to True for
    messages sent by the connected device). ``participant`` is set for
    group messages.
    """
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    key: dict = {"id": msg_id, "remoteJid": remote_jid}
    if participant is not None:
        key["participant"] = participant
    if from_me is not None:
        key["fromMe"] = from_me
    return {
        "key": key,
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


async def _make_adapter_in_live() -> WhatsAppChannelAdapter:
    """Construct an adapter and drive it to LIVE so messages are pushed."""
    a = WhatsAppChannelAdapter()
    await a.on_connection_open(trigger="initial_connect")
    await a.on_history_set()
    assert a.state == _WhatsAppSyncState.LIVE
    return a


async def _authed_handle(a: WhatsAppChannelAdapter, *, tenant: str = _TENANT):
    return await a.authenticate(
        SecretBundle(payload={
            "account_id": "wa-1",
            "tenant_id": tenant,
        })
    )


# --------------------------------------------------------------------------
# Path 1: key.fromMe == True
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_me_true_drops_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """key.fromMe == True → echo guard drops the message (returns None).

    This is the canonical Baileys signal and fires regardless of env
    configuration.
    """
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    peer_jid = "5511999999999@s.whatsapp.net"
    a.inject_message(
        peer_jid,
        _baileys_msg(remote_jid=peer_jid, from_me=True, body="bot's own"),
    )

    event = await a.fetch_latest_and_normalize(handle, peer_jid)
    assert event is None


@pytest.mark.asyncio
async def test_from_me_false_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """key.fromMe == False (and no jid match) → message normalized."""
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    peer_jid = "5511999999999@s.whatsapp.net"
    a.inject_message(
        peer_jid,
        _baileys_msg(remote_jid=peer_jid, from_me=False, body="real msg"),
    )

    event = await a.fetch_latest_and_normalize(handle, peer_jid)
    assert event is not None
    assert event.text == "real msg"


@pytest.mark.asyncio
async def test_neither_fromme_nor_jid_match_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare msg with no fromMe + bot env unset → normal pass-through."""
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    peer_jid = "5511999999999@s.whatsapp.net"
    # No fromMe field at all — common shape for inbound messages.
    a.inject_message(peer_jid, _baileys_msg(remote_jid=peer_jid, body="hi"))

    event = await a.fetch_latest_and_normalize(handle, peer_jid)
    assert event is not None
    assert event.text == "hi"


# --------------------------------------------------------------------------
# Path 2: sender jid matches bot's own jid
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_sender_jid_matches_bot_jid_drops_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DM where remoteJid (sender) == bot's own jid → echo dropped.

    Self-DMs are unusual but possible (e.g. WhatsApp "message yourself");
    additionally, on some Baileys versions self-sent DMs can surface
    with the bot's jid in remoteJid even when fromMe is unset on the
    inbound replay. Defensive coverage.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    # remoteJid IS the bot's jid; fromMe explicitly False (so path 1
    # does NOT fire — we're testing the jid-match path in isolation).
    a.inject_message(
        _BOT_JID,
        _baileys_msg(remote_jid=_BOT_JID, from_me=False, body="self-DM"),
    )

    event = await a.fetch_latest_and_normalize(handle, _BOT_JID)
    assert event is None


@pytest.mark.asyncio
async def test_dm_sender_jid_does_not_match_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DM where remoteJid is some other peer's jid → pass through."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    peer_jid = "5511999999999@s.whatsapp.net"
    a.inject_message(
        peer_jid,
        _baileys_msg(remote_jid=peer_jid, from_me=False, body="from peer"),
    )

    event = await a.fetch_latest_and_normalize(handle, peer_jid)
    assert event is not None
    assert event.text == "from peer"
    assert event.platform_user_id == peer_jid


# --------------------------------------------------------------------------
# Group messages — key.participant carries the actual sender
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_participant_matches_bot_jid_drops_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group msg where key.participant == bot's jid → echo dropped."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    group_jid = "120363012345678901@g.us"
    a.inject_message(
        group_jid,
        _baileys_msg(
            remote_jid=group_jid,
            participant=_BOT_JID,
            from_me=False,
            body="bot in group",
        ),
    )

    event = await a.fetch_latest_and_normalize(handle, group_jid)
    assert event is None


@pytest.mark.asyncio
async def test_group_participant_does_not_match_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group msg where key.participant is some other person → pass through."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    group_jid = "120363012345678901@g.us"
    other_jid = "5511777777777@s.whatsapp.net"
    a.inject_message(
        group_jid,
        _baileys_msg(
            remote_jid=group_jid,
            participant=other_jid,
            from_me=False,
            body="real group msg",
        ),
    )

    event = await a.fetch_latest_and_normalize(handle, group_jid)
    assert event is not None
    assert event.platform_user_id == other_jid
    assert event.text == "real group msg"


# --------------------------------------------------------------------------
# Bot phone env unset: jid-match no-ops, fromMe still works
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_phone_unset_jid_match_no_ops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env set + sender jid happens to look like a phone-shaped jid → pass through.

    Without env config we can't know which jid is "us"; the jid-match
    path returns False and the message is treated as normal inbound.
    """
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    # This jid would be the bot's if env were set, but env is unset.
    a.inject_message(
        _BOT_JID,
        _baileys_msg(remote_jid=_BOT_JID, from_me=False, body="ambiguous"),
    )

    event = await a.fetch_latest_and_normalize(handle, _BOT_JID)
    assert event is not None
    assert event.text == "ambiguous"


@pytest.mark.asyncio
async def test_bot_phone_unset_fromme_still_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with env unset, key.fromMe == True still triggers the drop."""
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    peer_jid = "5511999999999@s.whatsapp.net"
    a.inject_message(
        peer_jid,
        _baileys_msg(remote_jid=peer_jid, from_me=True, body="self echo"),
    )

    event = await a.fetch_latest_and_normalize(handle, peer_jid)
    assert event is None


# --------------------------------------------------------------------------
# Single-tenant fallback env: WORMBASE_WHATSAPP_BOT_PHONE (no suffix)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_env_fallback_resolves_bot_jid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant-scoped env unset, global env set → jid match still fires.

    Mirrors B1's resolution order:
      1. ``WORMBASE_WHATSAPP_BOT_PHONE_<TENANT>``
      2. ``WORMBASE_WHATSAPP_BOT_PHONE`` (single-tenant fallback)
    """
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", raising=False,
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _BOT_PHONE)

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    a.inject_message(
        _BOT_JID,
        _baileys_msg(remote_jid=_BOT_JID, from_me=False, body="echo"),
    )

    event = await a.fetch_latest_and_normalize(handle, _BOT_JID)
    assert event is None


@pytest.mark.asyncio
async def test_env_with_leading_plus_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E.164 ``+`` prefix in env is stripped before building the jid."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", f"+{_BOT_PHONE}",
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    a.inject_message(
        _BOT_JID,
        _baileys_msg(remote_jid=_BOT_JID, from_me=False, body="plus-prefixed"),
    )

    event = await a.fetch_latest_and_normalize(handle, _BOT_JID)
    assert event is None


# --------------------------------------------------------------------------
# Defensive: malformed payloads don't blow up the guard
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_key_dict_does_not_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload without a dict ``key`` → no echo signal; guard returns False.

    The downstream ``_normalize_message`` already tolerates a missing
    or non-dict key. The echo guard mirrors that tolerance: no key →
    no echo decision possible → don't drop.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{_TENANT.upper()}", _BOT_PHONE,
    )

    a = await _make_adapter_in_live()
    handle = await _authed_handle(a)
    jid = "5511999999999@s.whatsapp.net"
    # Build a payload with no key field at all.
    msg: dict = {
        "message": {"conversation": "no-key"},
        "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    a.inject_message(jid, msg)

    event = await a.fetch_latest_and_normalize(handle, jid)
    # Passes through to normalize; normalize tolerates missing key.
    assert event is not None
    assert event.text == "no-key"
