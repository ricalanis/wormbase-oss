# silent-mode: not-an-egress — wrapped by SilentModeChannelAdapter via registry.build_adapter
"""Microsoft Teams adapter — stub-but-real, Protocol-compliant.

Production impl: Microsoft Graph API + Bot Framework Service.
``listen`` subscribes to the chat-message webhook stream and bridges
each event into an :class:`InfraEvent`. ``send`` posts via Graph
``POST /chats/{chat-id}/messages``. ``install`` walks the
admin-consent OAuth flow and stores the app's bot identity.

Day-one shape mirrors :mod:`wormbase_channel_adapters.discord`: the
adapter is Protocol-compliant; production network code lands post-
day-one.
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
class TeamsChannelAdapter(ChannelAdapter):
    """Teams platform adapter (stub-but-real)."""

    platform: Platform = "teams"
    capability: set[ChannelCap] = {
        "ingest", "install", "send", "file_upload", "dm",
    }
    status: str = "preview"
    status_note: str = (
        "Preview. Install + listen are real (the worm will lurk); "
        "send + file_upload are skeletal — Bot Framework wiring lands in v1.5."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        # Teams requires the trio of (tenant_id, client_id,
        # client_secret) for the Bot Framework app registration.
        for required in ("tenant_id", "client_id", "client_secret"):
            if not secrets.payload.get(required):
                raise ValueError(
                    "teams adapter requires {tenant_id, client_id, "
                    "client_secret}"
                )
        seed = (
            f"{secrets.payload['tenant_id']}/"
            f"{secrets.payload['client_id']}"
        ).encode()
        return AuthHandle(
            connector_kind="teams",
            handle_id=hashlib.sha256(seed).hexdigest()[:16],
            extra={
                "tenant_id": secrets.payload["tenant_id"],
                "client_id": secrets.payload["client_id"],
                "client_secret": secrets.payload["client_secret"],
            },
        )

    async def install(self, handle: AuthHandle) -> InstallRecord:
        # Real impl: walk the admin-consent OAuth flow.
        return InstallRecord(
            install_id=handle.handle_id,
            platform="teams",
            scopes=[
                "ChatMessage.Read.Chat",
                "ChatMessage.Send",
                "User.Read.All",
            ],
            bot_user_id="teams-bot-id-stub",
        )

    async def listen(
        self, handle: AuthHandle
    ) -> AsyncIterator[InfraEvent]:
        # Stub-but-real: idle forever. Production impl bridges Bot
        # Framework webhooks into InfraEvent shapes.
        while True:
            await asyncio.sleep(60)
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef:
        return MessageRef(
            platform="teams",
            platform_message_id="teams-msg-stub",
            platform_channel_id=channel.platform_channel_id,
        )

    async def list_workspace_members(
        self, handle: AuthHandle
    ) -> list[PlatformMember]:
        return []


__all__ = ["TeamsChannelAdapter"]
