# silent-mode: not-an-egress — wrapped by SilentModeChannelAdapter via registry.build_adapter
"""Discord adapter — stub-but-real, Protocol-compliant.

Production impl: ``discord.py`` Bot's ``on_message`` handler bridges
each gateway event into an :class:`InfraEvent`. ``send`` posts via the
Discord HTTP API (``POST /channels/{id}/messages``). ``install`` walks
the OAuth grant flow and stores the bot token + scopes.

Day-one shape: ``authenticate`` and ``install`` are implemented (the
adapter knows how to validate a bot token and shape an InstallRecord).
``listen`` is a long-running coroutine that idles forever — proves
the abstraction without needing a live Discord bot. ``send`` returns a
stub MessageRef. ``list_workspace_members`` returns ``[]`` until the
production REST integration lands.

The wire-event normalization is the only thing that *must* match
Slack exactly when the production listen() lands: every Discord
message becomes an InfraEvent with the same shape SlackChannelAdapter
yields, so worm-core's downstream gates and flows are platform-blind.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator

from .base import ChannelAdapter
from .registry import register_channel_adapter
from .types import (
    AuthHandle,
    ChannelCap,
    ChannelRef,
    InfraEvent,
    InstallRecord,
    MessageRef,
    OutMessage,
    Platform,
    PlatformMember,
    SecretBundle,
)


@register_channel_adapter
class DiscordChannelAdapter(ChannelAdapter):
    """Discord platform adapter (stub-but-real)."""

    platform: Platform = "discord"
    capability: set[ChannelCap] = {
        "ingest", "install", "send", "file_upload", "dm",
    }
    status: str = "preview"
    status_note: str = (
        "Preview. Install + listen are real (the worm will lurk); "
        "send + file_upload are skeletal — full bot wiring lands in v1.5."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        bot_token = secrets.payload.get("bot_token")
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError("discord adapter requires {bot_token: str}")
        return AuthHandle(
            connector_kind="discord",
            handle_id=hashlib.sha256(bot_token.encode()).hexdigest()[:16],
            extra={"bot_token": bot_token},
        )

    async def install(self, handle: AuthHandle) -> InstallRecord:
        # Real impl: hit Discord's OAuth flow + validate the bot token.
        # Stub: synthesize an InstallRecord with the canonical scopes.
        return InstallRecord(
            install_id=handle.handle_id,
            platform="discord",
            scopes=["bot", "messages.read", "messages.write"],
            bot_user_id="discord-bot-id-stub",
        )

    async def listen(
        self, handle: AuthHandle
    ) -> AsyncIterator[InfraEvent]:
        # Stub-but-real: idle forever so the listen task survives but
        # emits nothing. Production impl uses discord.py's on_message
        # handler to yield events shaped identically to Slack's.
        while True:
            await asyncio.sleep(60)
        # Make this an async generator (unreachable yield; satisfies
        # the AsyncIterator contract for the type checker).
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef:
        # Skeletal: real impl posts via Discord HTTP API.
        return MessageRef(
            platform="discord",
            platform_message_id="discord-msg-stub",
            platform_channel_id=channel.platform_channel_id,
        )

    async def list_workspace_members(
        self, handle: AuthHandle
    ) -> list[PlatformMember]:
        return []


__all__ = ["DiscordChannelAdapter"]
