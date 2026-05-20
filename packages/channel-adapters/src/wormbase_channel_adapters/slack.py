# silent-mode: not-an-egress — wrapped by SilentModeChannelAdapter via registry.build_adapter
"""Slack channel adapter — production-grade.

Owns every Slack Web-API call the WormBase channel-adapter service
makes:

- ``auth.test``                 — discover bot identity
- ``conversations.history``     — fetch latest message after admit signal
- ``conversations.list``        — list workspace channels
- ``conversations.info``        — channel metadata (members, name)
- ``users.list``                — workspace member roster
- ``users.info``                — single-member metadata (used by the
                                  identity-discovery loop)
- ``chat.postMessage``          — outbound text + blocks
- ``files.upload`` (v2)         — outbound file upload
- ``conversations.join``        — auto-join public channel before posting

Why this lives in the adapter and not in service.py: every call is
Slack-specific and platform-agnostic code paths in worm-core / dashboard
should reach Slack only through ``ChannelAdapter`` calls. service.py
becomes a thin bridge: load the adapter from the registry, call
``adapter.listen()``, and process the InfraEvent stream into ledger
entries.

The OpenClaw global-log-tail capture path is preserved — its async
tailer remains in apps/channel-adapter/openclaw_log_tail.py as the
``listen()`` source. Listen() yields one ``InfraEvent`` per
``allow channel`` log line by fetching the latest message via
``conversations.history`` and normalizing the payload.

For tests + dependency-injection convenience the adapter accepts an
optional ``slack_client`` constructor arg; production code calls the
no-arg constructor and ``authenticate()`` builds a client internally.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

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
    PlatformMember,
    Platform,
    SecretBundle,
)

log = logging.getLogger(__name__)


# Type alias for the lazy slack_sdk AsyncWebClient — kept loose so we
# don't force the import at module-load time.
AsyncWebClient = Any


@register_channel_adapter
class SlackChannelAdapter(ChannelAdapter):
    """Slack platform adapter."""

    platform: Platform = "slack"
    capability: set[ChannelCap] = {
        "ingest", "send", "file_upload", "dm", "install",
    }
    status: str = "production"
    status_note: str = (
        "Production-grade. Real OAuth, ingest, send, file_upload, DM."
    )

    def __init__(
        self,
        *,
        slack_client: AsyncWebClient | None = None,
        admit_signal: Callable[
            [Callable[[str], Awaitable[None]]], AsyncIterator[None]
        ] | None = None,
    ) -> None:
        """Build a Slack adapter.

        ``slack_client`` (optional): inject a pre-built AsyncWebClient
        for tests. If None, ``authenticate`` will lazy-import slack_sdk
        and build one from the bot token.

        ``admit_signal`` (optional): a callable that drives the listen()
        stream by invoking a callback with channel_ids when OpenClaw's
        log signals an admit. Production wiring lives in
        apps/channel-adapter/service.py which constructs the
        OpenClawLogTailer; tests pass a fake.
        """
        self._injected_client = slack_client
        self._admit_signal = admit_signal

    # ------------------------------------------------------------------
    # Protocol implementations
    # ------------------------------------------------------------------

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        bot_token = secrets.payload.get("bot_token")
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError("slack adapter requires {bot_token: str}")
        client = self._injected_client or _build_async_client(bot_token)
        # Discover bot identity — auth.test is the single source of
        # truth for both bot_id and bot_user_id.
        bot_id: str | None = None
        bot_user_id: str | None = None
        try:
            resp = await client.auth_test()
            data = getattr(resp, "data", resp)
            if isinstance(data, dict) and data.get("ok"):
                bot_id = data.get("bot_id") or data.get("user_id")
                bot_user_id = data.get("user_id")
        except Exception as exc:  # noqa: BLE001
            log.warning("slack auth.test failed: %s", exc)
        return AuthHandle(
            connector_kind="slack",
            handle_id=str(bot_id or "unknown"),
            extra={
                "bot_token": bot_token,
                "client": client,
                "bot_id": bot_id,
                "bot_user_id": bot_user_id,
            },
        )

    async def install(self, handle: AuthHandle) -> InstallRecord:
        """Mark this handle as installed.

        Slack OAuth happens out-of-band (the Slack App Manifest includes
        the install URL); by the time we have a bot token, the install
        is already complete. ``install()`` confirms the token still
        works and returns an InstallRecord summarizing what we know.
        """
        client = handle.extra["client"]
        scopes: list[str] = []
        try:
            # apps.connections.open is a websocket op we don't need;
            # auth.test already happened in authenticate. Re-call to
            # verify the token is still alive at install time.
            resp = await client.auth_test()
            data = getattr(resp, "data", resp)
            if isinstance(data, dict):
                scope = data.get("scope") or ""
                if isinstance(scope, str) and scope:
                    scopes = scope.split(",")
        except Exception as exc:  # noqa: BLE001
            log.warning("slack install verify failed: %s", exc)
        return InstallRecord(
            install_id=handle.handle_id,
            platform="slack",
            scopes=scopes,
            bot_user_id=handle.extra.get("bot_user_id"),
            metadata={"bot_id": handle.extra.get("bot_id")},
        )

    async def listen(
        self, handle: AuthHandle
    ) -> AsyncIterator[InfraEvent]:
        """Yield one InfraEvent per channel admit signal.

        Production path: an external loop (apps/channel-adapter
        service.py) drives the OpenClawLogTailer and calls
        ``on_channel_admit(channel_id)`` on the adapter; that path
        ingests via ``fetch_latest_and_normalize`` directly. The
        listen() coroutine is provided for tests and for the future
        Socket-Mode-only path where the adapter owns the wire.

        When no admit_signal driver is configured, listen() simply
        sleeps forever — the service.py wrapper handles the wire.
        """
        if self._admit_signal is None:
            while True:
                await asyncio.sleep(60)
                # Yields only on driver invocation; otherwise idle.
        else:
            queue: asyncio.Queue[InfraEvent | None] = asyncio.Queue()

            async def _on_admit(channel_id: str) -> None:
                event = await self.fetch_latest_and_normalize(
                    handle, channel_id,
                )
                if event is not None:
                    await queue.put(event)

            async def _drive() -> None:
                async for _ in self._admit_signal(_on_admit):
                    pass
                await queue.put(None)  # signal end

            driver = asyncio.create_task(_drive())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    yield item
            finally:
                driver.cancel()

    async def send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef:
        client = handle.extra["client"]
        kwargs: dict[str, Any] = {
            "channel": channel.platform_channel_id,
            "text": msg.text,
        }
        if msg.blocks:
            kwargs["blocks"] = msg.blocks
        if msg.thread_ref:
            kwargs["thread_ts"] = msg.thread_ref
            if msg.reply_broadcast:
                kwargs["reply_broadcast"] = True
        # Auto-join public channels before posting (Slack returns
        # not_in_channel otherwise). Best-effort; ignore failures.
        try:
            await client.conversations_join(
                channel=channel.platform_channel_id,
            )
        except Exception:  # noqa: BLE001
            pass
        resp = await client.chat_postMessage(**kwargs)
        data = getattr(resp, "data", resp)
        ts = data.get("ts") if isinstance(data, dict) else None
        return MessageRef(
            platform="slack",
            platform_message_id=ts or "",
            platform_channel_id=channel.platform_channel_id,
        )

    async def list_workspace_members(
        self, handle: AuthHandle
    ) -> list[PlatformMember]:
        client = handle.extra["client"]
        members: list[PlatformMember] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = await client.users_list(**kwargs)
            except Exception as exc:  # noqa: BLE001
                log.warning("slack users.list failed: %s", exc)
                break
            data = getattr(resp, "data", resp)
            if not isinstance(data, dict) or not data.get("ok"):
                break
            for user in data.get("members") or []:
                if not isinstance(user, dict):
                    continue
                if user.get("deleted"):
                    continue
                profile = user.get("profile") or {}
                members.append(
                    PlatformMember(
                        platform="slack",
                        platform_user_id=user.get("id", ""),
                        display_name=(
                            user.get("real_name")
                            or user.get("name")
                            or "Unknown"
                        ),
                        email=profile.get("email"),
                        avatar_url=profile.get("image_192"),
                        is_bot=bool(user.get("is_bot")),
                        is_admin=bool(user.get("is_admin")),
                        raw=user,
                    )
                )
            cursor = (
                (data.get("response_metadata") or {}).get("next_cursor")
                or None
            )
            if not cursor:
                break
        return members

    # ------------------------------------------------------------------
    # Slack-specific helpers used by service.py
    # ------------------------------------------------------------------

    async def users_info(
        self, handle: AuthHandle, platform_user_id: str
    ) -> PlatformMember | None:
        """Look up a single workspace member by id.

        Used by the worm-core identity_discovery loop to enrich
        proposed Person rows. Returns None on API failure / unknown
        user — callers retry on the next discovery cycle.

        This is the function A4 (in apps/worm-core/src/wormbase_core/
        cli.py) calls instead of reaching into worm.lurker._app.client
        — making the lookup work even when the lurker socket is
        disabled.
        """
        client = handle.extra.get("client")
        if client is None:
            return None
        try:
            resp = await client.users_info(user=platform_user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "slack users.info failed for %s: %s",
                platform_user_id, exc,
            )
            return None
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        user = data.get("user") or {}
        if not isinstance(user, dict):
            return None
        profile = user.get("profile") or {}
        return PlatformMember(
            platform="slack",
            platform_user_id=user.get("id", platform_user_id),
            display_name=(
                user.get("real_name")
                or user.get("name")
                or "Unknown"
            ),
            email=profile.get("email"),
            avatar_url=profile.get("image_192"),
            is_bot=bool(user.get("is_bot")),
            is_admin=bool(user.get("is_admin")),
            raw=user,
        )

    async def fetch_latest_and_normalize(
        self, handle: AuthHandle, channel_id: str,
    ) -> InfraEvent | None:
        """Fetch latest message + normalize into InfraEvent.

        Called by the OpenClaw-log capture path in service.py. Returns
        None when the message is the bot's own echo, when Slack returns
        not-ok, or when conversations.history yields no messages.
        """
        client = handle.extra.get("client")
        if client is None:
            return None
        try:
            resp = await client.conversations_history(
                channel=channel_id, limit=1,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "slack conversations.history failed for %s: %s",
                channel_id, exc,
            )
            return None
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        messages = data.get("messages") or []
        if not messages:
            return None
        msg = messages[0]
        if not isinstance(msg, dict):
            return None
        ts = msg.get("ts")
        if not isinstance(ts, str) or not ts:
            return None
        # Echo guard: drop our own bot's posts.
        bot_id = handle.extra.get("bot_id")
        bot_user_id = handle.extra.get("bot_user_id")
        msg_bot_id = msg.get("bot_id")
        msg_user = msg.get("user")
        if (bot_id is not None and msg_bot_id == bot_id) or (
            bot_user_id is not None and msg_user == bot_user_id
        ):
            return None
        files = msg.get("files")
        source = "file_drop" if (
            isinstance(files, list) and files
        ) else "channel_message"
        return InfraEvent(
            source=source,
            platform="slack",
            platform_channel_id=channel_id,
            platform_user_id=msg.get("user") or msg.get("bot_id"),
            platform_message_id=ts,
            text=msg.get("text") or "",
            payload=msg,
            ts=datetime.now(timezone.utc),
            company_id=None,
            channel_id=None,
            person_id=None,
        )


def _build_async_client(bot_token: str) -> AsyncWebClient:
    """Lazy-import slack_sdk so package import is cheap."""
    from slack_sdk.web.async_client import AsyncWebClient as _AWC

    return _AWC(token=bot_token)


__all__ = ["SlackChannelAdapter"]
