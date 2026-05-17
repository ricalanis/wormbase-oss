"""Tests for WhatsApp adapter mentioned_jids extraction (Wave B1.1, 2026-05-06).

The plan locks the convention:

* WhatsApp messages WITH mentions → ``InfraEvent.mentioned_jids ==
  [<jid>, ...]`` (list of strings extracted from
  ``payload.message.extendedTextMessage.contextInfo.mentionedJid``).
* WhatsApp messages WITHOUT mentions (or with malformed nesting) →
  ``InfraEvent.mentioned_jids == []`` (empty list, NOT None — explicit
  empty distinguishes "WhatsApp said no mentions" from "non-WhatsApp
  adapter never populated this field").
* Slack / Discord / Teams adapters → ``InfraEvent.mentioned_jids is
  None`` (the InfraEvent dataclass default; no extraction performed
  there). Documents the per-adapter convention so a downstream consumer
  can distinguish "we know there are no mentions" (== []) from "we
  haven't checked" (== None).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from wormbase_channel_adapters.types import InfraEvent, SecretBundle
from wormbase_channel_adapters.whatsapp import WhatsAppChannelAdapter


_JID = "5511999999999@s.whatsapp.net"
_BOT_JID = "5511888888888@s.whatsapp.net"
_OTHER_JID = "5511777777777@s.whatsapp.net"


def _baileys_with_mentions(
    *,
    msg_id: str = "msg-1",
    jid: str = _JID,
    body: str = "hey",
    mentioned: list[str] | None = None,
    ts_unix: int | None = None,
) -> dict[str, Any]:
    """Build a Baileys-shaped extendedTextMessage with mentioned_jids."""
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    extended: dict[str, Any] = {"text": body}
    if mentioned is not None:
        extended["contextInfo"] = {"mentionedJid": mentioned}
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"extendedTextMessage": extended},
        "messageTimestamp": ts_unix,
    }


def _baileys_bare_conversation(
    *,
    msg_id: str = "msg-1",
    jid: str = _JID,
    body: str = "hey",
    ts_unix: int | None = None,
) -> dict[str, Any]:
    """A bare conversation message — no extendedTextMessage nesting."""
    if ts_unix is None:
        ts_unix = int(datetime.now(timezone.utc).timestamp())
    return {
        "key": {"id": msg_id, "remoteJid": jid},
        "message": {"conversation": body},
        "messageTimestamp": ts_unix,
    }


@pytest.fixture
async def adapter_handle() -> tuple[WhatsAppChannelAdapter, Any]:
    a = WhatsAppChannelAdapter(install_id="install-test")
    h = await a.authenticate(SecretBundle(payload={"account_id": "install-test"}))
    await a.on_history_set()  # short-circuit to LIVE for these tests
    return a, h


# ---------------------------------------------------------------------------
# 1. WhatsApp payload with mentions → InfraEvent.mentioned_jids populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_extended_text_with_mentions_populates_field(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A Baileys extendedTextMessage with contextInfo.mentionedJid →
    InfraEvent.mentioned_jids carries the same list."""
    adapter, handle = adapter_handle
    # Force LIVE mode so the message is push-classified.
    msg = _baileys_with_mentions(
        body=f"@{_BOT_JID.split('@')[0]} hi",
        mentioned=[_BOT_JID, _OTHER_JID],
    )
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert isinstance(event, InfraEvent)
    assert event.mentioned_jids == [_BOT_JID, _OTHER_JID]


@pytest.mark.asyncio
async def test_whatsapp_extended_text_with_single_mention(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A single-mention message round-trips as a single-element list."""
    adapter, handle = adapter_handle
    msg = _baileys_with_mentions(mentioned=[_BOT_JID])
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == [_BOT_JID]


# ---------------------------------------------------------------------------
# 2. WhatsApp payload without mentions → InfraEvent.mentioned_jids == []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_extended_text_no_context_info_yields_empty_list(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A WhatsApp message with no contextInfo nesting → empty list (not
    None)."""
    adapter, handle = adapter_handle
    msg = _baileys_with_mentions(mentioned=None)  # no contextInfo
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == []


@pytest.mark.asyncio
async def test_whatsapp_bare_conversation_yields_empty_list(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A bare ``message.conversation`` payload (no extendedTextMessage) →
    empty list. The adapter's _extract_mentioned_jids is permissive on
    every intermediate.
    """
    adapter, handle = adapter_handle
    msg = _baileys_bare_conversation()
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == []


@pytest.mark.asyncio
async def test_whatsapp_empty_mentioned_jids_list_round_trips(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A contextInfo with an explicit empty mentionedJid list → empty
    list on the InfraEvent (distinguishable from missing nesting)."""
    adapter, handle = adapter_handle
    msg = _baileys_with_mentions(mentioned=[])
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == []


# ---------------------------------------------------------------------------
# 3. Defensive: malformed payloads return [] (no exceptions).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_malformed_context_info_yields_empty_list(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """If contextInfo is the wrong type (e.g. a string), the extractor
    returns [] instead of raising."""
    adapter, handle = adapter_handle
    msg: dict[str, Any] = {
        "key": {"id": "m1", "remoteJid": _JID},
        "message": {
            "extendedTextMessage": {
                "text": "hey",
                "contextInfo": "not-a-dict",  # malformed
            },
        },
        "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == []


@pytest.mark.asyncio
async def test_whatsapp_non_string_jids_filtered_out(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """A mentionedJid list with non-string entries → only the strings
    survive. Defensive against malformed Baileys payloads.
    """
    adapter, handle = adapter_handle
    msg = _baileys_with_mentions(mentioned=[_BOT_JID, 12345, None, _OTHER_JID])  # type: ignore[list-item]
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == [_BOT_JID, _OTHER_JID]


@pytest.mark.asyncio
async def test_whatsapp_mentionedjid_wrong_type_yields_empty_list(
    adapter_handle: tuple[WhatsAppChannelAdapter, Any],
) -> None:
    """If mentionedJid itself is not a list (e.g. a dict), → []."""
    adapter, handle = adapter_handle
    msg: dict[str, Any] = {
        "key": {"id": "m1", "remoteJid": _JID},
        "message": {
            "extendedTextMessage": {
                "text": "hey",
                "contextInfo": {"mentionedJid": {"oops": "wrong type"}},
            },
        },
        "messageTimestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    adapter.inject_message(_JID, msg)
    event = await adapter.fetch_latest_and_normalize(handle, _JID)

    assert event is not None
    assert event.mentioned_jids == []


# ---------------------------------------------------------------------------
# 4. Static helper directly: WhatsAppChannelAdapter._extract_mentioned_jids.
# ---------------------------------------------------------------------------


def test_extract_helper_with_mentions() -> None:
    """Direct test of the static helper bypasses the state machine."""
    msg = _baileys_with_mentions(mentioned=[_BOT_JID, _OTHER_JID])
    assert WhatsAppChannelAdapter._extract_mentioned_jids(msg) == [
        _BOT_JID, _OTHER_JID,
    ]


def test_extract_helper_with_empty_message_dict() -> None:
    """Empty top-level dict → []."""
    assert WhatsAppChannelAdapter._extract_mentioned_jids({}) == []


def test_extract_helper_with_no_message_key() -> None:
    """Missing message subdict → []."""
    msg = {"key": {"id": "m1"}, "messageTimestamp": 0}
    assert WhatsAppChannelAdapter._extract_mentioned_jids(msg) == []


# ---------------------------------------------------------------------------
# 5. InfraEvent default convention — non-WhatsApp leaves mentioned_jids None.
# ---------------------------------------------------------------------------


def test_infraevent_mentioned_jids_default_is_none() -> None:
    """When constructed without ``mentioned_jids``, an InfraEvent leaves
    the field as ``None`` — Slack/Discord/Teams adapters never populate it.
    Distinguishes "non-WhatsApp adapter" from "WhatsApp said no mentions".
    """
    event = InfraEvent(
        source="channel_message",
        platform="slack",
        platform_channel_id="C123",
        platform_user_id="U123",
        platform_message_id="123.456",
        text="hi",
        payload={},
        ts=datetime.now(timezone.utc),
    )
    assert event.mentioned_jids is None
