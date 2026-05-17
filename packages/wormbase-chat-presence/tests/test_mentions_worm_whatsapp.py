"""WhatsApp-aware MentionsWorm predicate tests (Phase B1, 2026-05-06).

Slack regression checks live next to the original tests in
``test_predicates.py``; this file focuses on the new branch:

* Platform inference from ``channel_id`` (jid suffix)
* mentionedJid reads from both the normalized key and the canonical
  Baileys nesting
* Bot-phone env resolution (per-tenant + global fallback)
* Graceful failure when the bot phone env is unset

The Slack back-compat invariants (``test_mentions_worm_matches_handle``
and ``test_mentions_worm_misses_without_handle``) are repeated here as
a focused regression suite so a future refactor doesn't accidentally
re-route Slack events into the WhatsApp branch.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from wormbase_chat_presence.predicates import MentionsWorm
from wormbase_reactivities.protocol import ReactivityContext


# Stable UUIDs so env-var keys are deterministic across runs.
_TENANT_A = UUID("00000000-0000-0000-0000-0000000000aa")
_TENANT_B = UUID("00000000-0000-0000-0000-0000000000bb")
_BOT_PHONE_A = "15551234567"  # E.164 without leading '+'
_BOT_PHONE_B = "15557654321"
_BOT_JID_A = f"{_BOT_PHONE_A}@s.whatsapp.net"
_USER_JID = "15558675309@s.whatsapp.net"


def _ctx(company_id: UUID = _TENANT_A) -> ReactivityContext:
    return ReactivityContext(
        ledger=SimpleNamespace(),
        company_id=company_id,
        registry=None,
        now=lambda: None,
    )


def _whatsapp_entry(
    *,
    channel_id: str = _USER_JID,
    text: str = "",
    mentioned_jids: list[str] | None = None,
    baileys_payload: dict | None = None,
    extra_args: dict | None = None,
) -> dict:
    """Build a chat_received-shaped ledger entry.

    ``mentioned_jids`` populates the normalized key; ``baileys_payload``
    populates the canonical Baileys nesting under ``args.payload``.
    ``extra_args`` is merged last for ad-hoc overrides.
    """
    args: dict = {
        "channel_id": channel_id,
        "message_id": "wamid.test",
        "text": text,
        "classification": "internal",
    }
    if mentioned_jids is not None:
        args["mentioned_jids"] = mentioned_jids
    if baileys_payload is not None:
        args["payload"] = baileys_payload
    if extra_args:
        args.update(extra_args)
    return {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


def _slack_entry(text: str) -> dict:
    return {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": "C0AVTEST123",
                "message_id": "1746547200.000100",
                "text": text,
                "classification": "internal",
            },
        },
    }


# ---------------------------------------------------------------------------
# Slack back-compat — must remain byte-identical behavior.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slack_mention_with_handle_matches() -> None:
    p = MentionsWorm(handle="@worm")
    entry = _slack_entry("Hey @worm what is the churn rate?")
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_slack_message_without_handle_misses() -> None:
    p = MentionsWorm(handle="@worm")
    entry = _slack_entry("What is the churn rate?")
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_non_chat_entry_misses() -> None:
    """Regression: non-chat tools are filtered before any branch logic fires."""
    p = MentionsWorm(handle="@worm")
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "emit_source_proposed",
            "args": {"text": "@worm hi"},
        },
    }
    assert await p.match(entry, _ctx()) is False


# ---------------------------------------------------------------------------
# WhatsApp — normalized mentioned_jids key path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_mention_via_normalized_key_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When mentioned_jids carries the bot's jid → match."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        text="@15551234567 quick question",
        mentioned_jids=[_BOT_JID_A],
    )
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_whatsapp_mention_in_group_chat_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group chats use ``@g.us`` jids — still infer platform=whatsapp."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        channel_id="120363001234567890@g.us",
        text="@15551234567 thoughts on Q3?",
        mentioned_jids=[_BOT_JID_A],
    )
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_whatsapp_mention_without_bot_jid_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mentionedJid present but bot's jid not in the list → no match."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        text="@15551111111 hello",
        mentioned_jids=["15551111111@s.whatsapp.net"],
    )
    assert await p.match(entry, _ctx()) is False


# ---------------------------------------------------------------------------
# WhatsApp — canonical Baileys nesting path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_mention_via_baileys_nesting_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward-compat path: read mentionedJid from the raw Baileys payload.

    When the writer eventually plumbs InfraEvent.payload into
    ChatReceivedPayload args, this path activates without code changes.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        text="@15551234567 ping",
        baileys_payload={
            "key": {"id": "wamid.test", "remoteJid": _USER_JID},
            "message": {
                "extendedTextMessage": {
                    "text": "@15551234567 ping",
                    "contextInfo": {
                        "mentionedJid": [_BOT_JID_A],
                    },
                },
            },
            "messageTimestamp": 1746547200,
        },
    )
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_whatsapp_normalized_key_takes_precedence_over_baileys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If both paths are populated, the normalized key wins.

    Pins the contract: the writer's eventual normalization is the
    source of truth; the raw Baileys nesting is the fallback.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        text="@15551234567 ping",
        # Normalized: empty list (no mention)
        mentioned_jids=[],
        # Baileys nesting: bot's jid (would otherwise match)
        baileys_payload={
            "message": {
                "extendedTextMessage": {
                    "contextInfo": {"mentionedJid": [_BOT_JID_A]},
                },
            },
        },
    )
    # Normalized key wins → no match (empty list).
    assert await p.match(entry, _ctx()) is False


# ---------------------------------------------------------------------------
# WhatsApp — env var resolution behaviors.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_env_unset_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No bot phone env → predicate returns False (we don't know who we are)."""
    # Defensively delete both per-tenant and global keys.
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        raising=False,
    )
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        text="@15551234567 ping",
        mentioned_jids=[_BOT_JID_A],
    )
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_whatsapp_global_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-tenant env unset → fall back to global WORMBASE_WHATSAPP_BOT_PHONE."""
    monkeypatch.delenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        raising=False,
    )
    monkeypatch.setenv("WORMBASE_WHATSAPP_BOT_PHONE", _BOT_PHONE_A)
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(mentioned_jids=[_BOT_JID_A])
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_whatsapp_per_tenant_env_isolates_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant A's bot phone does not leak into tenant B's match decisions."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_B).upper()}",
        _BOT_PHONE_B,
    )
    monkeypatch.delenv("WORMBASE_WHATSAPP_BOT_PHONE", raising=False)
    p = MentionsWorm(handle="@worm")
    # Tenant A receives a message tagging tenant A's bot → match.
    entry_a = _whatsapp_entry(mentioned_jids=[_BOT_JID_A])
    assert await p.match(entry_a, _ctx(_TENANT_A)) is True
    # Same payload routed under tenant B's context → no match
    # (tenant B's bot has a different phone).
    assert await p.match(entry_a, _ctx(_TENANT_B)) is False


@pytest.mark.asyncio
async def test_whatsapp_phone_with_plus_prefix_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators sometimes set the env with a leading '+'; predicate strips it."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        f"+{_BOT_PHONE_A}",
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(mentioned_jids=[_BOT_JID_A])
    assert await p.match(entry, _ctx()) is True


# ---------------------------------------------------------------------------
# WhatsApp — graceful handling of malformed / sparse payloads.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_empty_payload_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No mentionedJid + no payload → no match (no crash)."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(text="hello")
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_whatsapp_malformed_baileys_nesting_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: non-dict intermediates in the Baileys path don't crash."""
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        # contextInfo is a string instead of a dict — payload is malformed.
        baileys_payload={
            "message": {
                "extendedTextMessage": {
                    "contextInfo": "not-a-dict",
                },
            },
        },
    )
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_whatsapp_explicit_platform_field_overrides_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward-compat: if a future writer emits args.platform, that wins.

    A Slack-shaped channel_id paired with explicit ``platform="whatsapp"``
    routes through the WhatsApp branch. Pins the precedence rule for the
    schema-evolution wave that adds the field.
    """
    monkeypatch.setenv(
        f"WORMBASE_WHATSAPP_BOT_PHONE_{str(_TENANT_A).upper()}",
        _BOT_PHONE_A,
    )
    p = MentionsWorm(handle="@worm")
    entry = _whatsapp_entry(
        channel_id="C0AVTEST123",  # Slack-shaped channel id
        mentioned_jids=[_BOT_JID_A],
        extra_args={"platform": "whatsapp"},
    )
    assert await p.match(entry, _ctx()) is True
