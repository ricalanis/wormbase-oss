# silent-mode: not-an-egress — type aliases / dataclasses
"""Shared types for the ChannelAdapter Protocol.

Every wire event normalizes into a single :class:`InfraEvent` shape.
Outbound messages flow through :class:`OutMessage` and are confirmed
via :class:`MessageRef`.

The ChannelAdapter package owns its own InfraEvent type even though
``wormbase_core.reactivity`` defines a structurally compatible one —
we don't want this package to depend on apps/worm-core (channel
adapters should be importable in isolation, before any worm-core code
loads). The service.py wrapper bridges between the two shapes when
processing the listen() stream into ledger entries.

Provenance fields (``delivery_mode`` / ``platform_ts`` / ``history_sync_id``)
distinguish freshly-pushed messages from historical bulk imports
(WhatsApp reconnect-history-replay, Slack stale-fetch). The derived
``is_live`` predicate is the canonical "should the speak-path fire"
gate; the substrate stays additive (no stored flag), and freshness
is computed against ``platform_ts`` with a 60s default window
(``WORMBASE_FRESHNESS_WINDOW_S`` env override).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# String aliases — the registry doesn't validate at this layer.
Platform = str  # "slack" | "discord" | "teams" | "whatsapp" | ...
ChannelCap = str  # "ingest" | "send" | "file_upload" | "dm" | "voice" | ...

# AdapterStatus drives capability honesty in the dashboard's channels
# tab. Production: every method is wired; preview: install + listen are
# real but send / file_upload may be stubbed; coming_soon: skeleton only.
AdapterStatus = Literal["production", "preview", "coming_soon"]


# Default freshness window for the is_live predicate (seconds). Permissive
# enough to absorb normal queueing latency; tight enough that an hour-old
# replayed message is correctly classified as stale.
_DEFAULT_FRESHNESS_WINDOW_S = 60.0


def _freshness_window_s() -> float:
    """Resolve the active freshness window from env, fall back to default.

    Env override is parsed once per call so tests can patch via
    ``monkeypatch.setenv`` without restarting the process.
    """
    raw = os.environ.get("WORMBASE_FRESHNESS_WINDOW_S")
    if not raw:
        return _DEFAULT_FRESHNESS_WINDOW_S
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_FRESHNESS_WINDOW_S


@dataclass(frozen=True)
class SecretBundle:
    """Opaque container for adapter credentials."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthHandle:
    """Returned by :meth:`ChannelAdapter.authenticate`."""

    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InstallRecord:
    """Result of :meth:`ChannelAdapter.install` — the OAuth grant landed."""

    install_id: str
    platform: Platform
    scopes: list[str]
    bot_user_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelRef:
    """Stable handle to a channel (or DM) on a platform."""

    platform: Platform
    platform_channel_id: str
    # WormBase-internal channel UUID resolved at ingest time. None at
    # platform-edge before resolve; populated by the time the event
    # reaches the dashboard.
    channel_id: str | None = None
    name: str | None = None
    is_dm: bool = False


@dataclass(frozen=True)
class PlatformMember:
    """One member of a platform workspace.

    ``platform_user_id`` is the platform-native id (Slack U..., Discord
    snowflake, Teams AAD object id). ``email`` is best-effort —
    Slack/Discord/Teams admin scopes return it; user scopes don't.
    """

    platform: Platform
    platform_user_id: str
    display_name: str
    email: str | None = None
    avatar_url: str | None = None
    is_bot: bool = False
    is_admin: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InfraEvent:
    """Normalized wire-event shape across every channel platform.

    Carries both ``platform_*`` raw native ids (so the adapter can
    re-call the platform without losing identity) and WormBase-internal
    ``channel_id`` / ``person_id`` (resolved at ingest time by the
    service.py bridge — None at the adapter edge).

    Provenance fields:
      * ``delivery_mode`` — "push" for live wire events; "history_sync"
        for messages replayed during a bulk reconnect/initial-connect.
      * ``platform_ts`` — the platform's authoritative wall-clock for the
        message (Slack ts, WhatsApp messageTimestamp). ``None`` when the
        platform doesn't surface one.
      * ``history_sync_id`` — UUID string pointing to the
        ``conversation_sync`` lineage entry that brought this message in.
        ``None`` for live (push) events.
      * ``mentioned_jids`` — list of WhatsApp jids explicitly mentioned in
        the message body. Slack/Discord/Teams adapters leave this
        ``None``; WhatsApp adapter populates from Baileys'
        ``payload.message.extendedTextMessage.contextInfo.mentionedJid``,
        falling back to an empty list when no mentions are present.
        (Wave B1.1, 2026-05-06.)

    The ``is_live`` property derives the speak-path gate from these
    fields plus the wall-clock ``ts`` and the configurable freshness
    window. Permissive when ``platform_ts`` is None (back-compat for
    pre-provenance entries).
    """

    source: Literal[
        "channel_message", "file_drop", "dm", "cron", "webhook",
        "reaction_added", "channel_admit",
    ]
    platform: Platform
    platform_channel_id: str | None
    platform_user_id: str | None
    platform_message_id: str | None
    text: str
    payload: dict[str, Any]
    ts: datetime
    company_id: str | None = None
    channel_id: str | None = None
    person_id: str | None = None
    delivery_mode: Literal["push", "history_sync"] = "push"
    platform_ts: datetime | None = None
    history_sync_id: str | None = None
    mentioned_jids: list[str] | None = None

    @property
    def is_live(self) -> bool:
        """Derived speak-path gate.

        ``True`` iff the event is push-delivered AND fresh (within the
        configured freshness window of ``platform_ts``). Permissive
        default: returns ``True`` when ``platform_ts`` is None so
        pre-provenance entries continue to flow.
        """
        if self.delivery_mode != "push":
            return False
        if self.platform_ts is None:
            return True
        return (self.ts - self.platform_ts).total_seconds() < _freshness_window_s()


@dataclass(frozen=True)
class OutMessage:
    """An outbound message the worm wants the adapter to send."""

    text: str
    blocks: list[dict[str, Any]] = field(default_factory=list)
    files: list[bytes] = field(default_factory=list)
    file_names: list[str] = field(default_factory=list)
    thread_ref: str | None = None
    reply_broadcast: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageRef:
    """Confirmation handle returned by :meth:`ChannelAdapter.send`."""

    platform: Platform
    platform_message_id: str
    platform_channel_id: str | None = None
    permalink: str | None = None


__all__ = [
    "AdapterStatus",
    "AuthHandle",
    "ChannelCap",
    "ChannelRef",
    "InfraEvent",
    "InstallRecord",
    "MessageRef",
    "OutMessage",
    "Platform",
    "PlatformMember",
    "SecretBundle",
]
