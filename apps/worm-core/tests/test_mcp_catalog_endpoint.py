"""Tests for the ``/mcp/catalog`` HTTP endpoint (Block J7 Phase A).

The dashboard's ``/mcp`` tab fetches this URL via
``WORMBASE_MCP_CATALOG_URL`` and renders the registered MCP surface
(tools, resources, prompts). The endpoint is read-only, bypasses
bearer-token auth (it serves a static introspection of the running
MCP server's surface, not per-tenant data), and is gated on
``WORMBASE_MCP_ENABLED``.

Coverage:

1. 200 with the full shape when ``WORMBASE_MCP_ENABLED=1``.
2. No auth required — request without an Authorization header still
   succeeds.
3. Deterministic shape across re-runs — calling the endpoint twice
   produces byte-identical JSON.
4. Lists exactly the registered tools / resources / prompts (parity
   with the FastMCP server registrations).
5. 404 with an honest body when the MCP server is disabled.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.mcp_server import build_catalog
from wormbase_core.mcp_tools.prompts import PROMPT_NAMES
from wormbase_core.mcp_tools.audit import AUDIT_TOOL_NAMES
from wormbase_core.mcp_tools.read_tools import READ_TOOL_NAMES
from wormbase_core.mcp_tools.resources import RESOURCE_URIS
from wormbase_core.mcp_tools.write_tools import WRITE_TOOL_NAMES
from wormbase_ledger import InMemoryLedger


API_TOKEN = "catalog-test-token"


@pytest_asyncio.fixture
async def enabled_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TestClient]:
    monkeypatch.setenv("WORMBASE_MCP_ENABLED", "1")
    app = build_app(ledger=InMemoryLedger(), api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


@pytest_asyncio.fixture
async def disabled_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TestClient]:
    # Be explicit: even if the surrounding shell sets it, this fixture wins.
    monkeypatch.delenv("WORMBASE_MCP_ENABLED", raising=False)
    app = build_app(ledger=InMemoryLedger(), api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


# ---------------------------------------------------------------------------
# Happy path — WORMBASE_MCP_ENABLED=1.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_endpoint_returns_full_shape(
    enabled_client: TestClient,
) -> None:
    """200 + full shape with tools, resources, prompts, and entries arrays."""
    async with enabled_client.get("/mcp/catalog") as resp:
        assert resp.status == 200
        body = await resp.json()
    assert body["available"] is True
    assert isinstance(body["entries"], list)
    assert isinstance(body["tools"], list)
    assert isinstance(body["resources"], list)
    assert isinstance(body["prompts"], list)
    # Every entry has the discriminated-union shape the dashboard expects.
    for entry in body["entries"]:
        assert entry["kind"] in ("tool", "resource", "prompt")
        assert isinstance(entry["name"], str) and entry["name"]
        assert "description" in entry


@pytest.mark.asyncio
async def test_catalog_endpoint_requires_no_auth(
    enabled_client: TestClient,
) -> None:
    """The catalog is a static introspection; no bearer token required."""
    # No Authorization header.
    async with enabled_client.get("/mcp/catalog") as resp:
        assert resp.status == 200
    # An obviously-wrong token still succeeds — the catalog ignores auth.
    async with enabled_client.get(
        "/mcp/catalog",
        headers={"Authorization": "Bearer not-a-real-token"},
    ) as resp:
        assert resp.status == 200


@pytest.mark.asyncio
async def test_catalog_lists_exactly_registered_surface(
    enabled_client: TestClient,
) -> None:
    """Catalog contents match the FastMCP server's registrations exactly."""
    async with enabled_client.get("/mcp/catalog") as resp:
        body = await resp.json()

    tool_names = {t["name"] for t in body["tools"]}
    expected_tools = (
        {"query_ledger"}
        | set(READ_TOOL_NAMES)
        | set(WRITE_TOOL_NAMES)
        | set(AUDIT_TOOL_NAMES)
    )
    assert tool_names == expected_tools, (
        f"tool catalog mismatch: extra={tool_names - expected_tools} "
        f"missing={expected_tools - tool_names}"
    )

    kind_by_name = {t["name"]: t["kind"] for t in body["tools"]}
    for n in WRITE_TOOL_NAMES:
        assert kind_by_name[n] == "write", (
            f"{n} should be classified as write; got {kind_by_name[n]!r}"
        )
    for n in READ_TOOL_NAMES:
        assert kind_by_name[n] == "read"
    for n in AUDIT_TOOL_NAMES:
        assert kind_by_name[n] == "audit", (
            f"{n} should be classified as audit; got {kind_by_name[n]!r}"
        )
    # Phase 0 query_ledger is a read tool.
    assert kind_by_name["query_ledger"] == "read"

    resource_uris = {r["uri_template"] for r in body["resources"]}
    assert resource_uris == set(RESOURCE_URIS), (
        f"resource catalog mismatch: extra={resource_uris - set(RESOURCE_URIS)} "
        f"missing={set(RESOURCE_URIS) - resource_uris}"
    )

    prompt_names = {p["name"] for p in body["prompts"]}
    assert prompt_names == set(PROMPT_NAMES), (
        f"prompt catalog mismatch: extra={prompt_names - set(PROMPT_NAMES)} "
        f"missing={set(PROMPT_NAMES) - prompt_names}"
    )

    # The flat ``entries`` array is the union of the three.
    assert len(body["entries"]) == (
        len(body["tools"]) + len(body["resources"]) + len(body["prompts"])
    )


@pytest.mark.asyncio
async def test_catalog_endpoint_is_deterministic(
    enabled_client: TestClient,
) -> None:
    """Two consecutive requests produce byte-identical JSON.

    Catalog contents come from a fresh FastMCP build each call. If any
    registration order is non-deterministic (e.g. a dict-order leak),
    this test catches it.
    """
    async with enabled_client.get("/mcp/catalog") as resp:
        body_a = await resp.text()
    async with enabled_client.get("/mcp/catalog") as resp:
        body_b = await resp.text()
    assert body_a == body_b


# ---------------------------------------------------------------------------
# Disabled gate — 404 with honest body.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_endpoint_404s_when_mcp_disabled(
    disabled_client: TestClient,
) -> None:
    async with disabled_client.get("/mcp/catalog") as resp:
        assert resp.status == 404
        body = await resp.json()
    assert body["available"] is False
    assert body["entries"] == []
    # Honest reason text — the dashboard surfaces this in its empty state.
    assert "WORMBASE_MCP_ENABLED" in body["reason"]


# ---------------------------------------------------------------------------
# Bonus: build_catalog() helper unit test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_catalog_helper_returns_full_shape() -> None:
    catalog = await build_catalog()
    assert catalog["available"] is True
    assert len(catalog["tools"]) == (
        1 + len(READ_TOOL_NAMES) + len(WRITE_TOOL_NAMES) + len(AUDIT_TOOL_NAMES)
    )
    assert len(catalog["resources"]) == len(RESOURCE_URIS)
    assert len(catalog["prompts"]) == len(PROMPT_NAMES)
    # Round-trips through JSON without error.
    json.dumps(catalog)
