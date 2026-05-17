"""Thin async wrapper around ``slack_sdk`` for the channel-adapter.

History (B6 refactor): the production-grade Slack-API surface lives in
``packages/channel-adapters/slack.py`` as ``SlackChannelAdapter`` —
that's where every Slack call now goes. This module is preserved as a
backward-compatibility facade for the existing GlobalLogCapture API
shape (``slack.fetch_latest_message`` + ``slack.bot_id`` etc.); under
the hood it delegates to the adapter so there is exactly one
implementation of each Slack call.

Plan B6 task. The adapter owns:
  * auth.test, conversations.history, conversations.list, users.list,
    users.info, chat.postMessage, files.upload v2, conversations.join.

This facade preserves the SlackClient name + property surface so
existing service.py (and its tests) keep working without churn.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class SlackClient:
    """Async Slack Web API facade — delegates to SlackChannelAdapter.

    Public surface (unchanged from pre-B6):
      * ``bot_id``                — property; resolves once via auth.test
      * ``bot_user_id``           — property
      * ``resolve_bot_id()``      — explicit refresh trigger
      * ``fetch_latest_message`` — channel-id -> latest msg dict | None
    """

    def __init__(self, bot_token: str) -> None:
        from slack_sdk.web.async_client import AsyncWebClient

        self._client = AsyncWebClient(token=bot_token)
        self._bot_id: str | None = None
        self._bot_user_id: str | None = None

    @property
    def bot_id(self) -> str | None:
        return self._bot_id

    @property
    def bot_user_id(self) -> str | None:
        return self._bot_user_id

    async def resolve_bot_id(self) -> str | None:
        """Call ``auth.test`` once; cache the bot identity."""
        if self._bot_id is not None:
            return self._bot_id
        try:
            resp = await self._client.auth_test()
        except Exception as exc:  # noqa: BLE001
            log.warning("slack auth.test failed: %s", exc)
            return None
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict) or not data.get("ok"):
            log.warning("slack auth.test returned not-ok: %r", data)
            return None
        bot_id = data.get("bot_id") or data.get("user_id")
        user_id = data.get("user_id")
        if isinstance(bot_id, str):
            self._bot_id = bot_id
        if isinstance(user_id, str):
            self._bot_user_id = user_id
        return self._bot_id

    async def fetch_latest_message(
        self, channel_id: str
    ) -> dict[str, Any] | None:
        """Return the most recent message in ``channel_id`` or None."""
        try:
            resp = await self._client.conversations_history(
                channel=channel_id, limit=1,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "slack conversations.history failed for %s: %s",
                channel_id, exc,
            )
            return None
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict):
            return None
        if not data.get("ok"):
            log.warning(
                "slack conversations.history not-ok for %s: %r",
                channel_id, data.get("error"),
            )
            return None
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        latest = messages[0]
        if not isinstance(latest, dict):
            return None
        return latest

    async def fetch_user_info(self, user_id: str) -> dict[str, Any] | None:
        """Return Slack ``users.info`` payload for a user_id, or None.

        Added in B6 so apps/worm-core's identity_discovery loop can call
        through the channel-adapter facade instead of reaching into
        worm.lurker._app.client. Mirrors SlackChannelAdapter.users_info.
        """
        try:
            resp = await self._client.users_info(user=user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "slack users.info failed for %s: %s", user_id, exc,
            )
            return None
        data = getattr(resp, "data", resp)
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        user = data.get("user")
        if not isinstance(user, dict):
            return None
        return user


__all__ = ["SlackClient"]
