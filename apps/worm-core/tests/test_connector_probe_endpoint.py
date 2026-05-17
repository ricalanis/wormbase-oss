"""GET /api/v1/connectors/{kind}/probe — Onboarding Sub-wave D.

Per-tenant probe of a connector's runtime health. Returns one of:
  works | degraded | failed | unknown

Honesty contract: kinds without a wired probe MUST return ``unknown``
with a reason — never ``works`` by default. This prevents the
marketplace from rendering a false-positive badge for connectors the
worm hasn't actually exercised.

Coverage:
- Always-available kind (csv_local) → ``works``.
- Production kind without a wired probe → ``unknown`` + reason.
- coming_soon kind → ``unknown`` + reason explaining the gap.
- Unknown kind → 404 with ``state="unknown"``.
- Read-only: no auth required (parallel to GET /api/v1/connectors).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-connector-probe"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


async def test_csv_local_probe_returns_works(client: TestClient) -> None:
    """csv_local is always-available → ``works`` honestly."""
    resp = await client.get("/api/v1/connectors/csv_local/probe")
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["kind"] == "csv_local"
    assert body["state"] == "works"
    assert body["reason"] is None


async def test_unknown_kind_returns_404_with_state_unknown(
    client: TestClient,
) -> None:
    """Unknown kind → 404 + ``state="unknown"`` for symmetric handling."""
    resp = await client.get("/api/v1/connectors/not_a_real_kind/probe")
    assert resp.status == 404
    body = await resp.json()
    assert body["state"] == "unknown"
    assert "unknown connector kind" in body["reason"]


async def test_probe_no_auth_required(client: TestClient) -> None:
    """Probe endpoint is read-only and doesn't require bearer auth."""
    resp = await client.get(
        "/api/v1/connectors/csv_local/probe",
        # Explicitly no Authorization header.
    )
    assert resp.status == 200


async def test_production_kind_without_wired_probe_returns_unknown(
    client: TestClient,
) -> None:
    """Production kinds whose probe isn't wired return honest ``unknown``.

    Stripe is registered as a connector kind (status=preview today, per
    the marketplace shell). The probe surface explicitly does NOT
    fake-positive for it; instead it returns ``unknown`` with a reason
    pointing operators at the source detail page.
    """
    from wormbase_lake_surfaces import default_registry

    registry = default_registry()
    # Pick any non-csv_local kind that's registered + not coming_soon.
    candidate: str | None = None
    for kind in registry.all_kinds():
        if kind == "csv_local":
            continue
        cls = registry.get(kind)
        if cls is None:
            continue
        if getattr(cls, "status", "preview") == "coming_soon":
            continue
        candidate = kind
        break
    assert candidate is not None, "expected at least one non-csv connector kind"

    resp = await client.get(f"/api/v1/connectors/{candidate}/probe")
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["state"] == "unknown"
    assert body["reason"]
    assert "probe not yet implemented" in body["reason"]


async def test_probe_response_shape_is_stable(
    client: TestClient,
) -> None:
    """Every probe response carries kind + state + reason keys."""
    resp = await client.get("/api/v1/connectors/csv_local/probe")
    assert resp.status == 200
    body = await resp.json()
    assert set(body.keys()) >= {"kind", "state", "reason"}
    # State must be one of the four allowed values.
    assert body["state"] in {"works", "degraded", "failed", "unknown"}
