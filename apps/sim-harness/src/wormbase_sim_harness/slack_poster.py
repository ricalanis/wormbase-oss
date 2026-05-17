"""SlackPoster — single-bot multi-persona poster.

Wraps ``slack_sdk.web.async_client.AsyncWebClient``. The bot must hold
the ``chat:write.customize`` scope; without it, ``username`` and
``icon_emoji`` overrides on ``chat.postMessage`` are silently ignored
and every post shows up under the bot's own identity.

File uploads: Slack's API does NOT let third-party callers attribute an
upload to a non-bot user. ``upload_as`` therefore uploads as the bot
account; the persona attribution comes from a follow-up text post that
references the file. This is documented in the engine flow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from slack_sdk.web.async_client import AsyncWebClient

from wormbase_sim_harness.personas import Persona

log = logging.getLogger(__name__)


class SlackPoster:
    """Async Slack Web API poster scoped to one bot token."""

    def __init__(
        self,
        bot_token: str,
        *,
        client: AsyncWebClient | None = None,
        mention_substitutions: dict[str, str] | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            from slack_sdk.web.async_client import AsyncWebClient

            self._client = AsyncWebClient(token=bot_token)
        # Cache of channel-name → channel-id resolutions. Required because
        # Slack's files.completeUploadExternal API rejects channel names
        # like "#todo-baseworm" — it only accepts IDs (regex ^[CGDZ][A-Z0-9]{8,}$).
        self._channel_id_cache: dict[str, str] = {}
        # Slack's API treats `@Name` in posted text as literal characters;
        # only `<@USER_ID>` becomes a real mention that fires `app_mention`.
        # Scenarios are authored with the readable form, so we substitute
        # at post time. Keys are the raw text to find (e.g. "@WormBase"),
        # values are the replacement (e.g. "<@U0AUSATGUB1>").
        self._mention_subs = mention_substitutions or {}

    def _apply_mention_subs(self, text: str) -> str:
        if not self._mention_subs or not text:
            return text
        for needle, replacement in self._mention_subs.items():
            text = text.replace(needle, replacement)
        return text

    async def _resolve_channel_id(self, channel: str) -> str:
        """Return the Slack channel ID for ``channel``.

        Accepts a literal id (``C0B06...``), a name (``#todo-baseworm``),
        or a bare name (``todo-baseworm``). IDs pass through unchanged.
        Names hit ``conversations.list`` once per name and are cached.
        """
        if channel.startswith("C") or channel.startswith("G") or channel.startswith("D"):
            # Already an id (regex check is sloppy but Slack will reject
            # genuine garbage on the actual call).
            return channel
        name = channel.lstrip("#")
        if name in self._channel_id_cache:
            return self._channel_id_cache[name]
        # Walk paginated channel list. types covers public + private.
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "types": "public_channel,private_channel",
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            resp = await self._client.conversations_list(**kwargs)
            data = getattr(resp, "data", resp)
            for ch in (data or {}).get("channels", []):
                if ch.get("name") == name:
                    self._channel_id_cache[name] = ch["id"]
                    return ch["id"]
            cursor = (data or {}).get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        raise ValueError(f"slack channel not found: {channel}")

    @property
    def client(self) -> AsyncWebClient:
        return self._client

    async def post_as(
        self,
        persona: Persona,
        channel: str,
        text: str,
    ) -> dict[str, Any]:
        """Call ``chat.postMessage`` with persona overrides."""
        text = self._apply_mention_subs(text)
        resp = await self._client.chat_postMessage(
            channel=channel,
            text=text,
            username=persona.display_name,
            icon_emoji=persona.icon_emoji,
        )
        data = getattr(resp, "data", resp)
        if isinstance(data, dict) and not data.get("ok", False):
            log.warning(
                "chat.postMessage not-ok: persona=%s channel=%s err=%r",
                persona.id,
                channel,
                data.get("error"),
            )
        return dict(data) if isinstance(data, dict) else {}

    async def upload_as(
        self,
        persona: Persona,
        channel: str,
        file_path: str | Path,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Upload ``file_path`` to ``channel``.

        Slack's Web API does not support per-call user attribution for
        file uploads — the file is owned by the bot account. Upstream
        (Path 3) treats the file's poster as the bot, but the surrounding
        scripted ``say`` posts (which DO carry persona overrides) make
        the conversation read naturally.

        Prefers ``files_upload_v2`` (the modern API); falls back to the
        deprecated ``files_upload`` if v2 isn't on the installed SDK.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"sim file not found: {path}")

        # files.completeUploadExternal requires the channel id (not name).
        channel_id = await self._resolve_channel_id(channel)

        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "file": str(path),
            "filename": path.name,
        }
        if caption:
            kwargs["initial_comment"] = caption

        upload_v2 = getattr(self._client, "files_upload_v2", None)
        if upload_v2 is not None:
            resp = await upload_v2(**kwargs)
        else:  # pragma: no cover — exercised only on very old slack-sdk.
            log.warning("files_upload_v2 unavailable; falling back to files.upload")
            resp = await self._client.files_upload(**kwargs)

        data = getattr(resp, "data", resp)
        if isinstance(data, dict) and not data.get("ok", False):
            log.warning(
                "files_upload_v2 not-ok: persona=%s channel=%s err=%r",
                persona.id,
                channel,
                data.get("error"),
            )
        return dict(data) if isinstance(data, dict) else {}


__all__ = ["SlackPoster"]
