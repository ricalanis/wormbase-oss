"""Tests for DiscordChannelAdapter (stub-but-real)."""

from __future__ import annotations

import asyncio

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.discord import DiscordChannelAdapter
from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)


def test_discord_protocol_compliance() -> None:
    a = DiscordChannelAdapter()
    assert isinstance(a, ChannelAdapter)
    assert a.platform == "discord"
    assert "ingest" in a.capability
    assert "install" in a.capability
    assert "send" in a.capability
    assert "file_upload" in a.capability
    assert "dm" in a.capability


def test_discord_declares_preview_status() -> None:
    """Discord install + listen are real; send/file_upload skeletal → preview."""
    a = DiscordChannelAdapter()
    assert a.status == "preview"
    assert isinstance(a.status_note, str) and a.status_note
    # The note must clearly mark what works vs what doesn't.
    assert "skeletal" in a.status_note.lower() or "preview" in a.status_note.lower()


@pytest.mark.asyncio
async def test_discord_authenticate_requires_bot_token() -> None:
    a = DiscordChannelAdapter()
    with pytest.raises(ValueError, match="bot_token"):
        await a.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_discord_authenticate_returns_handle() -> None:
    a = DiscordChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"bot_token": "abc.def.ghi"}),
    )
    assert handle.connector_kind == "discord"
    assert handle.extra["bot_token"] == "abc.def.ghi"


@pytest.mark.asyncio
async def test_discord_install_returns_record() -> None:
    a = DiscordChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"bot_token": "x"}),
    )
    install = await a.install(handle)
    assert install.platform == "discord"
    assert "bot" in install.scopes


@pytest.mark.asyncio
async def test_discord_send_returns_stub_ref() -> None:
    a = DiscordChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"bot_token": "x"}),
    )
    ref = await a.send(
        handle,
        ChannelRef(platform="discord", platform_channel_id="123"),
        OutMessage(text="hi"),
    )
    assert ref.platform == "discord"
    assert ref.platform_channel_id == "123"


@pytest.mark.asyncio
async def test_discord_list_workspace_members_empty() -> None:
    a = DiscordChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"bot_token": "x"}),
    )
    assert await a.list_workspace_members(handle) == []


@pytest.mark.asyncio
async def test_discord_listen_idles_until_cancelled() -> None:
    """listen() must be a survivable async generator that idles."""
    a = DiscordChannelAdapter()
    handle = await a.authenticate(
        SecretBundle(payload={"bot_token": "x"}),
    )

    async def consume() -> None:
        async for _ in a.listen(handle):
            return  # we shouldn't get here

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_discord_self_registers() -> None:
    from wormbase_channel_adapters.registry import default_registry

    cls = default_registry().get("discord")
    assert cls is DiscordChannelAdapter
