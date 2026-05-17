"""Tests for MCPConnector — mocked-transport unit tests.

The session factory is the seam: production binds it to the SDK's
Streamable-HTTP transport; tests inject a fake that records calls
and returns canned responses. No network in unit tests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from wormbase_lake_surfaces.base import Connector
from wormbase_lake_surfaces.mcp import (
    MCPConnector,
    MCPServerConfig,
    make_mcp_preset,
)
from wormbase_lake_surfaces.registry import default_registry
from wormbase_lake_surfaces.types import SecretBundle


# ---------------------------------------------------------------------------
# Fake MCP types — shaped like the SDK so Connector code paths exercise
# the same attribute reads. We don't import from `mcp` here so the test
# stays cheap to run (and provably exercises only our code).
# ---------------------------------------------------------------------------


@dataclass
class _FakeResource:
    uri: str
    name: str
    description: str = ""
    mimeType: str | None = None
    size: int | None = None


@dataclass
class _FakeListResourcesResult:
    resources: list[_FakeResource] = field(default_factory=list)


@dataclass
class _FakeTextContents:
    uri: str
    text: str
    mimeType: str = "text/plain"


@dataclass
class _FakeReadResourceResult:
    contents: list[Any] = field(default_factory=list)


class _FakeSession:
    """Mocked MCP ClientSession — records calls, returns canned data."""

    def __init__(
        self,
        *,
        resources: list[_FakeResource] | None = None,
        contents_by_uri: dict[str, list[Any]] | None = None,
    ) -> None:
        self.resources = resources or []
        self.contents_by_uri = contents_by_uri or {}
        self.initialized = False
        self.read_uris: list[str] = []

    async def initialize(self) -> None:
        self.initialized = True

    async def list_resources(self, cursor: str | None = None) -> Any:
        return _FakeListResourcesResult(resources=list(self.resources))

    async def read_resource(self, uri: Any) -> Any:
        key = str(uri)
        self.read_uris.append(key)
        # Strip pydantic AnyUrl trailing slash if any — match by prefix.
        contents = self.contents_by_uri.get(
            key, self.contents_by_uri.get(key.rstrip("/"), [])
        )
        return _FakeReadResourceResult(contents=list(contents))


def _factory_yielding(session: _FakeSession):
    """Build a session_factory closure that yields the given fake session."""

    @asynccontextmanager
    async def _factory(_config: MCPServerConfig, _secrets: SecretBundle):
        yield session

    return _factory


_TEST_CFG = MCPServerConfig(
    kind="mcp:test",
    server_url="https://test.example.com/mcp",
    required_secrets=("bearer_token",),
    classification_hints=("internal",),
    description="test fixture",
)


# ---------------------------------------------------------------------------
# Protocol + auth shape
# ---------------------------------------------------------------------------


def test_mcp_connector_implements_connector_protocol() -> None:
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(_FakeSession()))
    assert isinstance(c, Connector)
    assert c.kind == "mcp"
    assert c.capability == {"discover", "profile", "sample"}


def test_mcp_connector_requires_config() -> None:
    with pytest.raises(ValueError, match="MCPServerConfig"):
        MCPConnector()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_authenticate_rejects_missing_required_secret() -> None:
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(_FakeSession()))
    with pytest.raises(ValueError, match="bearer_token"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_authenticate_returns_stable_handle() -> None:
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(_FakeSession()))
    handle = await c.authenticate(
        SecretBundle(payload={"bearer_token": "abc-123"})
    )
    assert handle.connector_kind == "mcp:test"
    assert handle.handle_id and isinstance(handle.handle_id, str)
    assert handle.extra["server_url"] == "https://test.example.com/mcp"
    assert handle.extra["secrets"]["bearer_token"] == "abc-123"


@pytest.mark.asyncio
async def test_authenticate_handle_id_is_deterministic() -> None:
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(_FakeSession()))
    h1 = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    h2 = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    assert h1.handle_id == h2.handle_id


# ---------------------------------------------------------------------------
# discover()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_maps_mcp_resources_to_proposals() -> None:
    session = _FakeSession(
        resources=[
            _FakeResource(
                uri="mcp://test/users",
                name="Users",
                description="Workspace members",
                mimeType="application/json",
                size=1024,
            ),
            _FakeResource(
                uri="mcp://test/pages",
                name="Pages",
                description="Wiki pages",
                mimeType="text/markdown",
            ),
        ]
    )
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    proposals = await c.discover(handle)

    assert len(proposals) == 2
    assert proposals[0].resource_id == "mcp://test/users"
    assert proposals[0].name == "Users"
    assert proposals[0].kind == "endpoint"
    assert proposals[0].metadata["mimetype"] == "application/json"
    assert proposals[0].metadata["size_bytes"] == 1024
    assert proposals[0].classification_hint == "internal"
    assert session.initialized is True


@pytest.mark.asyncio
async def test_discover_skips_resources_without_uri() -> None:
    session = _FakeSession(
        resources=[
            _FakeResource(uri="mcp://test/ok", name="OK"),
            _FakeResource(uri="", name="bad"),  # type: ignore[arg-type]
        ]
    )
    # Force the `uri` to None on the second to mimic an SDK quirk.
    session.resources[1].uri = None  # type: ignore[assignment]
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    proposals = await c.discover(handle)
    assert len(proposals) == 1
    assert proposals[0].name == "OK"


@pytest.mark.asyncio
async def test_discover_returns_empty_when_no_resources() -> None:
    session = _FakeSession(resources=[])
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    assert await c.discover(handle) == []


# ---------------------------------------------------------------------------
# profile()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_extracts_text_size_and_line_count() -> None:
    session = _FakeSession(
        contents_by_uri={
            "mcp://test/page1": [
                _FakeTextContents(
                    uri="mcp://test/page1",
                    text="line1\nline2\nline3\n",
                    mimeType="text/markdown",
                )
            ]
        }
    )
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    profile = await c.profile(handle, "mcp://test/page1")

    assert profile.row_count == 3  # newlines
    assert profile.column_count is None  # MCP doesn't expose schema
    assert profile.columns == []
    assert profile.schema_hash != ""
    assert profile.extra["mimetype"] == "text/markdown"
    assert profile.extra["bytes"] == len("line1\nline2\nline3\n")
    assert profile.extra["resource_id"] == "mcp://test/page1"


@pytest.mark.asyncio
async def test_profile_handles_empty_contents() -> None:
    session = _FakeSession(contents_by_uri={"mcp://test/blank": []})
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    profile = await c.profile(handle, "mcp://test/blank")
    assert profile.extra["bytes"] == 0
    assert profile.extra["mimetype"] == "application/octet-stream"
    assert profile.row_count is None  # not text/* mimetype


# ---------------------------------------------------------------------------
# sample()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_returns_first_n_bytes() -> None:
    session = _FakeSession(
        contents_by_uri={
            "mcp://test/x": [
                _FakeTextContents(
                    uri="mcp://test/x",
                    text="abcdefghij",
                    mimeType="text/plain",
                )
            ]
        }
    )
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    sample = await c.sample(handle, "mcp://test/x", 4)
    assert sample == b"abcd"


@pytest.mark.asyncio
async def test_sample_zero_n_returns_empty_bytes() -> None:
    session = _FakeSession(
        contents_by_uri={
            "mcp://test/x": [
                _FakeTextContents(uri="mcp://test/x", text="abc")
            ]
        }
    )
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(session))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    assert await c.sample(handle, "mcp://test/x", 0) == b""


# ---------------------------------------------------------------------------
# watch()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_yields_nothing_in_v1() -> None:
    c = MCPConnector(config=_TEST_CFG, session_factory=_factory_yielding(_FakeSession()))
    handle = await c.authenticate(SecretBundle(payload={"bearer_token": "tok"}))
    items = [item async for item in c.watch(handle, "mcp://test/x")]
    assert items == []


# ---------------------------------------------------------------------------
# make_mcp_preset() — preset-class factory
# ---------------------------------------------------------------------------


def test_make_mcp_preset_produces_registrable_subclass() -> None:
    cfg = MCPServerConfig(
        kind="mcp:_test_preset_unique",
        server_url="https://example.test/mcp",
        required_secrets=("bearer_token",),
    )
    cls = make_mcp_preset(cfg, register=False)
    try:
        assert issubclass(cls, MCPConnector)
        assert cls.kind == "mcp:_test_preset_unique"
        assert cls.server_config is cfg
        assert cls.status == "preview"
        # Instantiable without args (config bound at class level).
        instance = cls()
        assert instance.config is cfg
    finally:
        # cls wasn't registered; no cleanup needed.
        assert default_registry().get("mcp:_test_preset_unique") is None


def test_make_mcp_preset_self_registers_when_register_true() -> None:
    cfg = MCPServerConfig(
        kind="mcp:_test_register_unique",
        server_url="https://example.test/mcp",
        required_secrets=("bearer_token",),
    )
    cls = make_mcp_preset(cfg, register=True)
    try:
        assert default_registry().get("mcp:_test_register_unique") is cls
    finally:
        default_registry().unregister("mcp:_test_register_unique")
