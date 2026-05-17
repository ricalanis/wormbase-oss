"""Integration tests — multi-tenant MCP HTTP routing (Path 4, 2026-05-21).

Verifies the Optional-Effect Injection Case 5 contract end-to-end
through the FastMCP server:

  1. Default OFF (deps.tenant_router=None) preserves byte-identical
     single-tenant behavior — every v2.A test in the suite stays green.
  2. Tenant resolution via injected header reader: known slug routes
     to the registered company_id.
  3. Missing X-Tenant-Slug → DeniedResponse with tenant_unknown code.
  4. Unknown slug → DeniedResponse with tenant_unknown code.
  5. Revoked tenant → DeniedResponse with tenant_revoked code.
  6. Rate-limit exceeded → DeniedResponse with rate_limited code.
  7. Per-tenant rate-limit isolation (tenant A hitting limit does not
     spill into tenant B).
  8. Quota tracking — consumed counters tick per call.
  9. Replay determinism — slug→company_id resolution is uuid5-stable.

The header reader is injected into the FastMCP server via a test
seam: we monkeypatch ``get_http_request`` in the server module to
return a fake request carrying the slug we want for each call. In
production, FastMCP exposes the real inbound HTTP request.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch
from uuid import UUID

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server
from wormbase_agent_gateway.tenancy import (
    InMemoryQuotaTracker,
    InMemoryRateLimiter,
    InMemoryTenantRouter,
)

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake HTTP request — injected via monkeypatch in place of get_http_request
# ---------------------------------------------------------------------------


_SLUG_HOLDER: dict[str, str | None] = {"slug": None}


def _fake_header_reader() -> str | None:
    """Replacement for ``_get_tenant_slug_header_for_request`` in tests."""
    return _SLUG_HOLDER["slug"]


@contextmanager
def _slug_context(slug: str | None):
    prev = _SLUG_HOLDER["slug"]
    _SLUG_HOLDER["slug"] = slug
    try:
        yield
    finally:
        _SLUG_HOLDER["slug"] = prev


@pytest.fixture
def patched_http_request():
    """Patch the agent-gateway module-level header reader.

    Done at the module-level helper (not the FastMCP dependency) so
    that FastMCP's own internal use of ``get_http_request`` for
    routing/transport is unaffected.
    """
    with patch(
        "wormbase_agent_gateway.mcp_server.server."
        "_get_tenant_slug_header_for_request",
        new=_fake_header_reader,
    ):
        yield


# ---------------------------------------------------------------------------
# Helper — wire a router onto a GatewayHarness
# ---------------------------------------------------------------------------


def _wire_tenant_router(
    harness,
    *,
    tenants: list[str],
    rate_limiter: InMemoryRateLimiter | None = None,
    quota_tracker: InMemoryQuotaTracker | None = None,
) -> InMemoryTenantRouter:
    router = InMemoryTenantRouter(
        rate_limiter=rate_limiter,
        quota_tracker=quota_tracker,
    )
    for slug in tenants:
        router.register(tenant_slug=slug)
    harness.deps = replace(harness.deps, tenant_router=router)
    return router


# ---------------------------------------------------------------------------
# 1. Default OFF preserves byte-identical single-tenant behavior
# ---------------------------------------------------------------------------


async def test_single_tenant_default_off_preserves_behavior(gateway_deps_factory):
    """Without tenant_router (default), the server uses deps.company_id.

    A call that would denial-due-to-grant resolves identically to the
    v2.A / v2.B baseline; tenant header is ignored.
    """
    harness = gateway_deps_factory()
    assert harness.deps.tenant_router is None  # documented default
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool("lake.catalog.tables", {})
    # Should not be a tenant-pre-auth denial.
    parsed = unwrap(result)
    gate_name = parsed.get("gate_name", "")
    assert not gate_name.startswith("tenant:"), (
        "single-tenant default should not invoke tenant pre-auth"
    )


# ---------------------------------------------------------------------------
# 2. Known slug routes to the registered company_id
# ---------------------------------------------------------------------------


async def test_known_slug_resolves_to_registered_company_id(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    router = _wire_tenant_router(harness, tenants=["acme"])
    server = build_agent_gateway_mcp_server(harness.deps)

    # Wire a side-effect-recording catalog_reader so we can verify the
    # company_id passed in matches the slug's resolved UUID.
    seen_company_ids: list[UUID] = []

    async def _recording_list_tables(*, company_id, filter):
        seen_company_ids.append(company_id)
        return []

    harness.catalog_reader.list_tables = _recording_list_tables  # type: ignore[assignment]

    with _slug_context("acme"):
        async with Client(server.mcp) as client:
            await client.call_tool("lake.catalog.tables", {})

    assert len(seen_company_ids) == 1
    # Compute the expected company_id from the router record.
    expected = next(iter(router._tenants.values())).company_id  # type: ignore[attr-defined]
    assert seen_company_ids[0] == expected
    # And it must differ from the harness default (proves the swap happened).
    assert seen_company_ids[0] != harness.deps.company_id


# ---------------------------------------------------------------------------
# 3. Missing X-Tenant-Slug returns DeniedResponse with tenant_unknown
# ---------------------------------------------------------------------------


async def test_missing_slug_returns_tenant_unknown_denial(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    _wire_tenant_router(harness, tenants=["acme"])
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context(None):
        async with Client(server.mcp) as client:
            result = await client.call_tool("lake.catalog.tables", {})
    parsed = unwrap(result)
    assert parsed.get("status") == "denied"
    assert parsed.get("gate_name") == "tenant:tenant_unknown"
    assert parsed.get("audit_trail_id") == "tenant-pre-auth"


# ---------------------------------------------------------------------------
# 4. Unknown slug returns DeniedResponse with tenant_unknown
# ---------------------------------------------------------------------------


async def test_unknown_slug_returns_tenant_unknown_denial(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    _wire_tenant_router(harness, tenants=["acme"])
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context("nope"):
        async with Client(server.mcp) as client:
            result = await client.call_tool("lake.catalog.tables", {})
    parsed = unwrap(result)
    assert parsed.get("status") == "denied"
    assert parsed.get("gate_name") == "tenant:tenant_unknown"
    assert "nope" in (parsed.get("reason") or "")


# ---------------------------------------------------------------------------
# 5. Revoked tenant returns DeniedResponse with tenant_revoked
# ---------------------------------------------------------------------------


async def test_revoked_slug_returns_tenant_revoked_denial(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    router = _wire_tenant_router(harness, tenants=["acme"])
    router.revoke("acme")
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context("acme"):
        async with Client(server.mcp) as client:
            result = await client.call_tool("lake.catalog.tables", {})
    parsed = unwrap(result)
    assert parsed.get("status") == "denied"
    assert parsed.get("gate_name") == "tenant:tenant_revoked"


# ---------------------------------------------------------------------------
# 6. Rate-limit exceeded returns DeniedResponse with rate_limited
# ---------------------------------------------------------------------------


async def test_rate_limit_exceeded_returns_denial(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    rate_limiter = InMemoryRateLimiter(
        capacity_per_min=2, window_seconds=60.0,
    )
    _wire_tenant_router(
        harness, tenants=["acme"], rate_limiter=rate_limiter,
    )
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context("acme"):
        async with Client(server.mcp) as client:
            # First two calls succeed (no tenant-pre-auth denial).
            for _ in range(2):
                result = await client.call_tool("lake.catalog.tables", {})
                parsed = unwrap(result)
                gate_name = parsed.get("gate_name") or ""
                assert not gate_name.startswith("tenant:"), (
                    "first two calls should not hit the tenant gate"
                )
            # Third call exceeds the limit.
            result = await client.call_tool("lake.catalog.tables", {})
            parsed = unwrap(result)
            assert parsed.get("status") == "denied"
            assert parsed.get("gate_name") == "tenant:rate_limited"


# ---------------------------------------------------------------------------
# 7. Per-tenant rate-limit isolation
# ---------------------------------------------------------------------------


async def test_rate_limit_does_not_cross_contaminate_tenants(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    rate_limiter = InMemoryRateLimiter(
        capacity_per_min=1, window_seconds=60.0,
    )
    _wire_tenant_router(
        harness, tenants=["acme", "beta"], rate_limiter=rate_limiter,
    )
    server = build_agent_gateway_mcp_server(harness.deps)

    async with Client(server.mcp) as client:
        # acme: 1st OK, 2nd rate-limited.
        with _slug_context("acme"):
            r1 = await client.call_tool("lake.catalog.tables", {})
            r2 = await client.call_tool("lake.catalog.tables", {})
        # beta: 1st should still be OK.
        with _slug_context("beta"):
            r3 = await client.call_tool("lake.catalog.tables", {})

    p1 = unwrap(r1)
    p2 = unwrap(r2)
    p3 = unwrap(r3)
    assert not (p1.get("gate_name") or "").startswith("tenant:")
    assert p2.get("gate_name") == "tenant:rate_limited"
    assert not (p3.get("gate_name") or "").startswith("tenant:"), (
        "tenant beta should not inherit tenant acme's rate-limit state"
    )


# ---------------------------------------------------------------------------
# 8. Quota tracking ticks per call
# ---------------------------------------------------------------------------


async def test_quota_consumed_per_call(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    quota_tracker = InMemoryQuotaTracker(
        capacity_per_day=10, window_seconds=86400.0,
    )
    router = _wire_tenant_router(
        harness, tenants=["acme"], quota_tracker=quota_tracker,
    )
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context("acme"):
        async with Client(server.mcp) as client:
            for _ in range(3):
                await client.call_tool("lake.catalog.tables", {})

    snap = router.snapshot("acme")
    quota = snap["quota"]
    assert isinstance(quota, dict)
    assert quota.get("consumed") == 3


async def test_quota_exhaustion_returns_quota_exceeded_denial(
    gateway_deps_factory, patched_http_request,
):
    harness = gateway_deps_factory()
    quota_tracker = InMemoryQuotaTracker(
        capacity_per_day=2, window_seconds=86400.0,
    )
    _wire_tenant_router(
        harness, tenants=["acme"], quota_tracker=quota_tracker,
    )
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context("acme"):
        async with Client(server.mcp) as client:
            await client.call_tool("lake.catalog.tables", {})
            await client.call_tool("lake.catalog.tables", {})
            result = await client.call_tool("lake.catalog.tables", {})
    parsed = unwrap(result)
    assert parsed.get("status") == "denied"
    assert parsed.get("gate_name") == "tenant:quota_exceeded"


# ---------------------------------------------------------------------------
# 9. Replay determinism — slug→company_id is uuid5-stable
# ---------------------------------------------------------------------------


async def test_slug_resolution_is_deterministic(
    gateway_deps_factory, patched_http_request,
):
    """A recorded request with X-Tenant-Slug=acme always resolves to
    the same company_id, on every replay, every machine. Required for
    wire-replay determinism (CLAUDE.md §1 substrate commitment)."""
    seen: list[UUID] = []

    async def _recording_list_tables(*, company_id, filter):
        seen.append(company_id)
        return []

    # Build the harness + server fresh twice; assert same company_id.
    for _ in range(2):
        harness = gateway_deps_factory()
        _wire_tenant_router(harness, tenants=["acme"])
        harness.catalog_reader.list_tables = _recording_list_tables  # type: ignore[assignment]
        server = build_agent_gateway_mcp_server(harness.deps)
        with _slug_context("acme"):
            async with Client(server.mcp) as client:
                await client.call_tool("lake.catalog.tables", {})

    assert len(seen) == 2
    assert seen[0] == seen[1], (
        "slug→company_id resolution must be deterministic across builds"
    )


# ---------------------------------------------------------------------------
# 10. Subscription tools also resolve tenant correctly
# ---------------------------------------------------------------------------


async def test_subscription_tools_honor_tenant_router(
    gateway_deps_factory, patched_http_request,
):
    """The subscription tool surface also goes through tenant resolution.
    With no slug, it returns the tenant_unknown denial, not the
    "subscriptions not configured" denial."""
    harness = gateway_deps_factory()
    _wire_tenant_router(harness, tenants=["acme"])
    server = build_agent_gateway_mcp_server(harness.deps)

    with _slug_context(None):
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "agent.subscriptions.list",
                {"agent_id": harness.agent_id.value},
            )
    parsed = unwrap(result)
    # Tenant pre-auth denial supersedes the not-configured denial.
    assert parsed.get("status") == "denied"
    assert parsed.get("gate_name") == "tenant:tenant_unknown"
