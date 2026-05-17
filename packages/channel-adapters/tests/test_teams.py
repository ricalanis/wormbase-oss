"""Tests for TeamsChannelAdapter (stub-but-real)."""

from __future__ import annotations

import asyncio

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.teams import TeamsChannelAdapter
from wormbase_channel_adapters.types import (
    ChannelRef,
    OutMessage,
    SecretBundle,
)

_GOOD_SECRETS = {
    "tenant_id": "abc-tenant",
    "client_id": "abc-client",
    "client_secret": "shhh",
}


def test_teams_protocol_compliance() -> None:
    a = TeamsChannelAdapter()
    assert isinstance(a, ChannelAdapter)
    assert a.platform == "teams"
    assert "ingest" in a.capability
    assert "install" in a.capability


def test_teams_declares_preview_status() -> None:
    a = TeamsChannelAdapter()
    assert a.status == "preview"
    assert isinstance(a.status_note, str) and a.status_note
    assert "skeletal" in a.status_note.lower() or "preview" in a.status_note.lower()


@pytest.mark.asyncio
async def test_teams_authenticate_requires_full_trio() -> None:
    a = TeamsChannelAdapter()
    for missing in ("tenant_id", "client_id", "client_secret"):
        partial = dict(_GOOD_SECRETS)
        partial.pop(missing)
        with pytest.raises(ValueError, match="tenant_id, client_id, client_secret"):
            await a.authenticate(SecretBundle(payload=partial))


@pytest.mark.asyncio
async def test_teams_authenticate_returns_handle() -> None:
    a = TeamsChannelAdapter()
    handle = await a.authenticate(SecretBundle(payload=_GOOD_SECRETS))
    assert handle.connector_kind == "teams"
    assert handle.extra["tenant_id"] == "abc-tenant"


@pytest.mark.asyncio
async def test_teams_install_returns_record() -> None:
    a = TeamsChannelAdapter()
    handle = await a.authenticate(SecretBundle(payload=_GOOD_SECRETS))
    install = await a.install(handle)
    assert install.platform == "teams"
    assert "ChatMessage.Send" in install.scopes


@pytest.mark.asyncio
async def test_teams_send_returns_stub_ref() -> None:
    a = TeamsChannelAdapter()
    handle = await a.authenticate(SecretBundle(payload=_GOOD_SECRETS))
    ref = await a.send(
        handle,
        ChannelRef(platform="teams", platform_channel_id="chat:1"),
        OutMessage(text="hi"),
    )
    assert ref.platform == "teams"
    assert ref.platform_channel_id == "chat:1"


@pytest.mark.asyncio
async def test_teams_list_workspace_members_empty() -> None:
    a = TeamsChannelAdapter()
    handle = await a.authenticate(SecretBundle(payload=_GOOD_SECRETS))
    assert await a.list_workspace_members(handle) == []


@pytest.mark.asyncio
async def test_teams_listen_idles_until_cancelled() -> None:
    a = TeamsChannelAdapter()
    handle = await a.authenticate(SecretBundle(payload=_GOOD_SECRETS))

    async def consume() -> None:
        async for _ in a.listen(handle):
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_teams_self_registers() -> None:
    from wormbase_channel_adapters.registry import default_registry

    cls = default_registry().get("teams")
    assert cls is TeamsChannelAdapter
