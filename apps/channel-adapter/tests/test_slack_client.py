"""Tests for the thin async SlackClient wrapper.

We don't talk to real Slack — we patch ``AsyncWebClient`` with an
``AsyncMock`` instance and assert the wrapper:

  * caches ``bot_id`` after one successful ``auth.test``;
  * returns None on auth.test errors and not-ok responses;
  * returns the latest message dict on successful ``conversations.history``;
  * returns None on not-ok / SlackApiError / empty messages list.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from wormbase_channel_adapter.slack_client import SlackClient


def _resp(data: dict) -> SimpleNamespace:
    """Mimic ``slack_sdk`` SlackResponse — exposes ``.data`` and dict-like."""
    return SimpleNamespace(data=data)


def _make_client_with_async_mock() -> tuple[SlackClient, AsyncMock]:
    """Build a SlackClient whose underlying AsyncWebClient is an AsyncMock.

    We can't simply construct ``SlackClient(...)`` because its __init__
    imports and instantiates ``AsyncWebClient``. Patch the import path
    used inside __init__.
    """
    fake = AsyncMock()
    with patch(
        "slack_sdk.web.async_client.AsyncWebClient",
        return_value=fake,
    ):
        client = SlackClient("xoxb-test")
    # Sanity: the real AsyncWebClient was replaced.
    assert client._client is fake  # type: ignore[attr-defined]
    return client, fake


class TestResolveBotId:
    @pytest.mark.asyncio
    async def test_happy_path_caches_bot_id(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.auth_test = AsyncMock(
            return_value=_resp(
                {"ok": True, "bot_id": "B0BOT001", "user_id": "U0USER001"}
            )
        )
        bid = await client.resolve_bot_id()
        assert bid == "B0BOT001"
        assert client.bot_id == "B0BOT001"

        # A second call must NOT hit auth_test again — cached on the instance.
        bid2 = await client.resolve_bot_id()
        assert bid2 == "B0BOT001"
        assert fake.auth_test.await_count == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_user_id_when_bot_id_missing(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.auth_test = AsyncMock(
            return_value=_resp({"ok": True, "user_id": "U0FALLBACK"})
        )
        bid = await client.resolve_bot_id()
        assert bid == "U0FALLBACK"

    @pytest.mark.asyncio
    async def test_returns_none_on_not_ok(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.auth_test = AsyncMock(
            return_value=_resp({"ok": False, "error": "invalid_auth"})
        )
        assert await client.resolve_bot_id() is None
        assert client.bot_id is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.auth_test = AsyncMock(side_effect=RuntimeError("network down"))
        assert await client.resolve_bot_id() is None
        assert client.bot_id is None


class TestFetchLatestMessage:
    @pytest.mark.asyncio
    async def test_returns_message_dict_on_ok(self) -> None:
        client, fake = _make_client_with_async_mock()
        message = {
            "ts": "1777152782.692639",
            "user": "U0AV4C8TTEZ",
            "text": "hello",
        }
        fake.conversations_history = AsyncMock(
            return_value=_resp({"ok": True, "messages": [message]})
        )
        out = await client.fetch_latest_message("C0CHANNEL01")
        assert out == message
        fake.conversations_history.assert_awaited_once_with(
            channel="C0CHANNEL01", limit=1
        )

    @pytest.mark.asyncio
    async def test_returns_none_on_not_ok(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.conversations_history = AsyncMock(
            return_value=_resp({"ok": False, "error": "channel_not_found"})
        )
        assert await client.fetch_latest_message("C0BAD") is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_messages(self) -> None:
        client, fake = _make_client_with_async_mock()
        fake.conversations_history = AsyncMock(
            return_value=_resp({"ok": True, "messages": []})
        )
        assert await client.fetch_latest_message("C0EMPTY") is None

    @pytest.mark.asyncio
    async def test_returns_none_on_slack_api_error(self) -> None:
        client, fake = _make_client_with_async_mock()
        # Simulate slack_sdk.errors.SlackApiError without importing it
        # (keeps the test independent of slack_sdk's exception layout).
        fake.conversations_history = AsyncMock(
            side_effect=Exception("rate limited")
        )
        assert await client.fetch_latest_message("C0RATE") is None
