"""Tests for SlackChannelAdapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.slack import SlackChannelAdapter
from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)


def test_slack_implements_channel_adapter() -> None:
    a = SlackChannelAdapter()
    assert isinstance(a, ChannelAdapter)
    assert a.platform == "slack"
    assert "ingest" in a.capability
    assert "send" in a.capability
    assert "file_upload" in a.capability
    assert "dm" in a.capability


def test_slack_declares_production_status() -> None:
    a = SlackChannelAdapter()
    assert a.status == "production"
    assert isinstance(a.status_note, str) and a.status_note


def _fake_client(**responses: Any) -> Any:
    """Build a MagicMock-backed AsyncWebClient stand-in.

    Pass keyword args to seed responses for specific Slack methods,
    e.g. ``_fake_client(auth_test={"ok": True, "bot_id": "B1"})``.
    """
    client = MagicMock()
    for method, payload in responses.items():
        resp = MagicMock()
        resp.data = payload
        setattr(client, method, AsyncMock(return_value=resp))
    return client


@pytest.mark.asyncio
async def test_slack_authenticate_requires_bot_token() -> None:
    a = SlackChannelAdapter()
    with pytest.raises(ValueError, match="bot_token"):
        await a.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_slack_authenticate_resolves_bot_identity() -> None:
    client = _fake_client(
        auth_test={"ok": True, "bot_id": "B123", "user_id": "U456"},
    )
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    assert handle.connector_kind == "slack"
    assert handle.extra["bot_id"] == "B123"
    assert handle.extra["bot_user_id"] == "U456"
    assert handle.handle_id == "B123"


@pytest.mark.asyncio
async def test_slack_authenticate_survives_auth_test_failure() -> None:
    """A failed auth.test must still return a handle (degraded mode).

    The discovery loop tolerates missing bot_id; we don't want to hard-
    fail authenticate every time Slack rate-limits us.
    """
    client = MagicMock()
    client.auth_test = AsyncMock(side_effect=RuntimeError("rate limited"))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    assert handle.connector_kind == "slack"
    assert handle.extra["bot_id"] is None


@pytest.mark.asyncio
async def test_slack_install_records_scopes() -> None:
    client = _fake_client(
        auth_test={
            "ok": True,
            "bot_id": "B1",
            "user_id": "U1",
            "scope": "chat:write,channels:read,users:read",
        },
    )
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    install = await a.install(handle)
    assert install.platform == "slack"
    assert install.bot_user_id == "U1"
    assert "chat:write" in install.scopes


@pytest.mark.asyncio
async def test_slack_send_posts_message_and_returns_ref() -> None:
    client = _fake_client(
        auth_test={"ok": True, "bot_id": "B1"},
        chat_postMessage={"ok": True, "ts": "1234.5678"},
        conversations_join={"ok": True},
    )
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    ref = await a.send(
        handle,
        ChannelRef(platform="slack", platform_channel_id="C99"),
        OutMessage(text="hi"),
    )
    assert ref.platform == "slack"
    assert ref.platform_message_id == "1234.5678"
    assert ref.platform_channel_id == "C99"
    client.chat_postMessage.assert_awaited_once()
    args = client.chat_postMessage.call_args
    assert args.kwargs["channel"] == "C99"
    assert args.kwargs["text"] == "hi"


@pytest.mark.asyncio
async def test_slack_send_threads_when_thread_ref_set() -> None:
    client = _fake_client(
        auth_test={"ok": True},
        chat_postMessage={"ok": True, "ts": "9.0"},
        conversations_join={"ok": True},
    )
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    await a.send(
        handle,
        ChannelRef(platform="slack", platform_channel_id="C99"),
        OutMessage(text="thread reply", thread_ref="1.0"),
    )
    args = client.chat_postMessage.call_args
    assert args.kwargs["thread_ts"] == "1.0"


@pytest.mark.asyncio
async def test_slack_list_workspace_members_paginates() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={"ok": True}))
    page1 = MagicMock(data={
        "ok": True,
        "members": [
            {
                "id": "U1",
                "name": "alice",
                "real_name": "Alice",
                "profile": {"email": "alice@x.com", "image_192": None},
                "is_bot": False,
                "is_admin": False,
                "deleted": False,
            },
            {
                "id": "UDEAD",
                "deleted": True,
            },
        ],
        "response_metadata": {"next_cursor": "next1"},
    })
    page2 = MagicMock(data={
        "ok": True,
        "members": [
            {
                "id": "U2",
                "name": "bob",
                "real_name": "Bob",
                "profile": {"email": "bob@x.com"},
                "is_bot": False,
                "is_admin": True,
            },
        ],
        "response_metadata": {"next_cursor": ""},
    })
    client.users_list = AsyncMock(side_effect=[page1, page2])
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    members = await a.list_workspace_members(handle)
    assert [m.platform_user_id for m in members] == ["U1", "U2"]
    assert members[0].email == "alice@x.com"
    assert members[1].is_admin is True
    assert client.users_list.await_count == 2


@pytest.mark.asyncio
async def test_slack_users_info_returns_member_for_known_user() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={"ok": True}))
    client.users_info = AsyncMock(return_value=MagicMock(data={
        "ok": True,
        "user": {
            "id": "Uxyz",
            "real_name": "Xyz Person",
            "name": "xyz",
            "profile": {"email": "xyz@x.com", "image_192": "https://x"},
            "is_bot": False,
            "is_admin": False,
        },
    }))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    member = await a.users_info(handle, "Uxyz")
    assert member is not None
    assert member.display_name == "Xyz Person"
    assert member.email == "xyz@x.com"
    assert member.avatar_url == "https://x"


@pytest.mark.asyncio
async def test_slack_users_info_returns_none_when_not_ok() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={"ok": True}))
    client.users_info = AsyncMock(return_value=MagicMock(
        data={"ok": False, "error": "user_not_found"},
    ))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    assert await a.users_info(handle, "Uxyz") is None


@pytest.mark.asyncio
async def test_slack_users_info_returns_none_on_exception() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={"ok": True}))
    client.users_info = AsyncMock(side_effect=RuntimeError("boom"))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    assert await a.users_info(handle, "Uxyz") is None


@pytest.mark.asyncio
async def test_slack_fetch_latest_and_normalize() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={
        "ok": True, "bot_id": "BSELF", "user_id": "USELF",
    }))
    client.conversations_history = AsyncMock(return_value=MagicMock(data={
        "ok": True,
        "messages": [
            {
                "ts": "1.000001",
                "user": "U1",
                "text": "hello world",
            },
        ],
    }))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    event = await a.fetch_latest_and_normalize(handle, "C123")
    assert event is not None
    assert event.source == "channel_message"
    assert event.platform == "slack"
    assert event.platform_channel_id == "C123"
    assert event.platform_user_id == "U1"
    assert event.platform_message_id == "1.000001"
    assert event.text == "hello world"


@pytest.mark.asyncio
async def test_slack_fetch_latest_skips_self_echo() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={
        "ok": True, "bot_id": "BSELF", "user_id": "USELF",
    }))
    client.conversations_history = AsyncMock(return_value=MagicMock(data={
        "ok": True,
        "messages": [
            {
                "ts": "1.0",
                "bot_id": "BSELF",
                "text": "I just posted this",
            },
        ],
    }))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    assert await a.fetch_latest_and_normalize(handle, "C1") is None


@pytest.mark.asyncio
async def test_slack_fetch_latest_marks_file_drop_when_files_present() -> None:
    client = MagicMock()
    client.auth_test = AsyncMock(return_value=MagicMock(data={"ok": True}))
    client.conversations_history = AsyncMock(return_value=MagicMock(data={
        "ok": True,
        "messages": [
            {
                "ts": "1.0",
                "user": "U1",
                "text": "sales-q3.csv",
                "files": [{"id": "F1", "name": "sales-q3.csv"}],
            },
        ],
    }))
    a = SlackChannelAdapter(slack_client=client)
    handle = await a.authenticate(SecretBundle(payload={"bot_token": "xoxb"}))
    event = await a.fetch_latest_and_normalize(handle, "C1")
    assert event is not None
    assert event.source == "file_drop"
    assert event.payload.get("files") == [
        {"id": "F1", "name": "sales-q3.csv"},
    ]


def test_slack_self_registers() -> None:
    from wormbase_channel_adapters.registry import default_registry

    cls = default_registry().get("slack")
    assert cls is SlackChannelAdapter
