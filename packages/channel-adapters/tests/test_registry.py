"""Registry-shape tests for the ChannelAdapter Protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.registry import (
    ChannelAdapterRegistry,
    register_channel_adapter,
)
from wormbase_channel_adapters.types import (
    AuthHandle,
    ChannelRef,
    InfraEvent,
    InstallRecord,
    MessageRef,
    OutMessage,
    PlatformMember,
    SecretBundle,
)


class _FakeAdapter:
    platform = "fake"
    capability: set[str] = {"ingest", "send"}
    status: str = "preview"
    status_note: str = "test fixture"

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        return AuthHandle(connector_kind="fake", handle_id="x", extra={})

    async def install(self, handle: AuthHandle) -> InstallRecord:
        return InstallRecord(
            install_id="x",
            platform="fake",
            scopes=[],
            bot_user_id=None,
        )

    async def listen(self, handle: AuthHandle) -> AsyncIterator[InfraEvent]:
        if False:
            yield  # type: ignore[unreachable]

    async def send(
        self, handle: AuthHandle, channel: ChannelRef, msg: OutMessage,
    ) -> MessageRef:
        return MessageRef(platform="fake", platform_message_id="m1")

    async def list_workspace_members(
        self, handle: AuthHandle,
    ) -> list[PlatformMember]:
        return []


def test_registry_lookup() -> None:
    reg = ChannelAdapterRegistry()
    reg.register(_FakeAdapter)
    cls = reg.get("fake")
    assert cls is _FakeAdapter


def test_registry_rejects_duplicates() -> None:
    reg = ChannelAdapterRegistry()
    reg.register(_FakeAdapter)
    with pytest.raises(ValueError):
        reg.register(_FakeAdapter)


def test_registry_unknown_returns_none() -> None:
    reg = ChannelAdapterRegistry()
    assert reg.get("does-not-exist") is None


def test_registry_rejects_class_with_no_platform() -> None:
    class _NoPlatform:
        capability: set[str] = set()

    reg = ChannelAdapterRegistry()
    with pytest.raises(ValueError):
        reg.register(_NoPlatform)


def test_registry_all_platforms_sorted() -> None:
    reg = ChannelAdapterRegistry()
    reg.register(_FakeAdapter)

    class _Other(_FakeAdapter):
        platform = "alpha"

    reg.register(_Other)
    assert reg.all_platforms() == ["alpha", "fake"]


def test_registry_membership() -> None:
    reg = ChannelAdapterRegistry()
    reg.register(_FakeAdapter)
    assert "fake" in reg
    assert "missing" not in reg
    assert len(reg) == 1


def test_registry_unregister() -> None:
    reg = ChannelAdapterRegistry()
    reg.register(_FakeAdapter)
    reg.unregister("fake")
    assert reg.get("fake") is None


def test_fake_satisfies_channel_adapter_protocol() -> None:
    a = _FakeAdapter()
    assert isinstance(a, ChannelAdapter)


def test_register_decorator() -> None:
    """The decorator registers in default_registry and returns the class."""
    from wormbase_channel_adapters.registry import default_registry

    @register_channel_adapter
    class _Decorated(_FakeAdapter):
        platform = "decorated_test_unique_xyz"

    try:
        assert (
            default_registry().get("decorated_test_unique_xyz")
            is _Decorated
        )
    finally:
        default_registry().unregister("decorated_test_unique_xyz")


def test_infra_event_round_trip() -> None:
    """InfraEvent is a frozen dataclass and stores both raw + resolved ids."""
    e = InfraEvent(
        source="channel_message",
        platform="fake",
        platform_channel_id="C123",
        platform_user_id="U123",
        platform_message_id="ts.0001",
        text="hello",
        payload={"raw": "blob"},
        ts=datetime.now(timezone.utc),
        company_id=None,
        channel_id=None,
        person_id=None,
    )
    # frozen
    with pytest.raises(Exception):
        e.text = "mutated"  # type: ignore[misc]
    assert e.platform_channel_id == "C123"
