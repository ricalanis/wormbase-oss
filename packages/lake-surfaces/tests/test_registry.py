"""Registry-shape tests — Protocol compliance, lookup, dedup."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from wormbase_lake_surfaces.base import Connector
from wormbase_lake_surfaces.registry import ConnectorRegistry, register_connector
from wormbase_lake_surfaces.types import (
    AuthHandle,
    Change,
    Profile,
    ResourceProposal,
    SecretBundle,
)


class _FakeConnector:
    kind = "fake"
    capability: set[str] = {"discover", "profile"}
    classification_hints: list[str] = []
    status: str = "preview"
    status_note: str = "test fixture"

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        return AuthHandle(connector_kind="fake", handle_id="x", extra={})

    async def discover(self, handle: AuthHandle) -> list[ResourceProposal]:
        return []

    async def profile(self, handle: AuthHandle, resource_id: str) -> Profile:
        return Profile(
            row_count=0, column_count=0, columns=[], schema_hash="", extra={},
        )

    async def sample(
        self, handle: AuthHandle, resource_id: str, n: int
    ) -> bytes:
        return b""

    async def watch(
        self, handle: AuthHandle, resource_id: str
    ) -> AsyncIterator[Change]:
        if False:
            yield  # type: ignore[unreachable]


def test_registry_lookup() -> None:
    reg = ConnectorRegistry()
    reg.register(_FakeConnector)
    cls = reg.get("fake")
    assert cls is _FakeConnector


def test_registry_rejects_duplicates() -> None:
    reg = ConnectorRegistry()
    reg.register(_FakeConnector)
    with pytest.raises(ValueError):
        reg.register(_FakeConnector)


def test_registry_unknown_returns_none() -> None:
    reg = ConnectorRegistry()
    assert reg.get("does-not-exist") is None


def test_registry_rejects_class_with_no_kind() -> None:
    class _NoKind:
        capability: set[str] = set()
        classification_hints: list[str] = []

    reg = ConnectorRegistry()
    with pytest.raises(ValueError):
        reg.register(_NoKind)


def test_registry_all_kinds_sorted() -> None:
    reg = ConnectorRegistry()
    reg.register(_FakeConnector)

    class _Other(_FakeConnector):
        kind = "alpha"

    reg.register(_Other)
    assert reg.all_kinds() == ["alpha", "fake"]


def test_registry_membership() -> None:
    reg = ConnectorRegistry()
    reg.register(_FakeConnector)
    assert "fake" in reg
    assert "missing" not in reg
    assert len(reg) == 1


def test_registry_unregister() -> None:
    reg = ConnectorRegistry()
    reg.register(_FakeConnector)
    reg.unregister("fake")
    assert reg.get("fake") is None


def test_fake_satisfies_connector_protocol() -> None:
    c = _FakeConnector()
    assert isinstance(c, Connector)


def test_register_connector_decorator() -> None:
    """The decorator returns the class and registers in default_registry."""
    from wormbase_lake_surfaces.registry import default_registry

    @register_connector
    class _DecoratedConnector(_FakeConnector):
        kind = "decorated_test_unique"

    try:
        assert default_registry().get("decorated_test_unique") is _DecoratedConnector
    finally:
        default_registry().unregister("decorated_test_unique")
