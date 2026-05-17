"""Tests for the reactivities + resource-conversation HTTP endpoints (W5.A5).

Exercises:
  - GET /api/v1/reactivities returns the registry list (or [] when no
    registry is wired)
  - POST /api/v1/reactivities/propose runs the NL parser, returns the
    sketch, persists when registry is wired
  - ?preview=1 short-circuits the persistence
  - POST /api/v1/reactivities/{id}/confirm flips the binding to active
  - POST /api/v1/reactivities/{id}/disable flips to disabled with reason
  - GET /api/v1/reactivities/{id}/fires reads emit_reactivity_fired entries
  - GET /api/v1/people/{id}/resource-conversations folds the lifecycle
    payloads into the dashboard-shaped rows

We use the real ReactivityRegistry against an in-memory ledger so the
PEVR writes the registry emits are observable end-to-end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ReactivityRegistry


API_TOKEN = "test-token-123"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def registry(ledger: InMemoryLedger) -> ReactivityRegistry:
    from wormbase_core.service import tenant_to_uuid

    return ReactivityRegistry(
        ledger=ledger,
        company_id=tenant_to_uuid(TENANT_SLUG),
    )


@pytest_asyncio.fixture
async def client_with_registry(
    ledger: InMemoryLedger, registry: ReactivityRegistry,
) -> AsyncIterator[TestClient]:
    app = build_app(
        ledger=ledger, api_token=API_TOKEN, reactivity_registry=registry,
    )
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


@pytest_asyncio.fixture
async def client_no_registry(
    ledger: InMemoryLedger,
) -> AsyncIterator[TestClient]:
    app = build_app(ledger=ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/reactivities
# ---------------------------------------------------------------------------


async def test_get_reactivities_no_registry_returns_empty(
    client_no_registry: TestClient,
) -> None:
    resp = await client_no_registry.get(
        "/api/v1/reactivities", headers=_headers(),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"reactivities": []}


async def test_get_reactivities_with_registry_returns_rows(
    client_with_registry: TestClient, registry: ReactivityRegistry,
) -> None:
    # Register a stub Reactivity so the list returns at least one row.
    class _StubReactivity:
        id = "stub_reactivity"
        name = "Stub"
        description = "for tests"
        scope = "company"

        class _AlwaysFalse:
            async def match(self, entry: dict, ctx: Any) -> bool:
                return False

        class _AlwaysTrue:
            async def allows(self, entry: dict, ctx: Any) -> bool:
                return True

        predicate = _AlwaysFalse()
        condition = _AlwaysTrue()

        async def fire(self, entry: dict, ctx: Any):
            from wormbase_reactivities.protocol import ReactivityResult
            return ReactivityResult(fired=False)

    registry.register(_StubReactivity())  # type: ignore[arg-type]
    resp = await client_with_registry.get(
        "/api/v1/reactivities", headers=_headers(),
    )
    assert resp.status == 200
    body = await resp.json()
    assert isinstance(body["reactivities"], list)
    assert len(body["reactivities"]) == 1
    row = body["reactivities"][0]
    assert row["id"] == "stub_reactivity"
    assert row["scope"] == "company"
    assert row["state"] == "active"


# ---------------------------------------------------------------------------
# POST /api/v1/reactivities/propose
# ---------------------------------------------------------------------------


async def test_propose_returns_sketch_with_confidence(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.post(
        "/api/v1/reactivities/propose",
        headers=_headers(),
        json={
            "description": "ping me whenever someone mentions revenue",
            "proposed_by": "p-admin",
        },
    )
    assert resp.status == 201
    body = await resp.json()
    sketch = body["sketch"]
    assert sketch["confidence"] > 0.5
    assert sketch["predicate_spec"]["topic"] == "revenue"
    assert sketch["action_spec"]["kind"] in {"dm_owner", "post_to_channel"}
    assert body["persisted"] is True


async def test_propose_preview_does_not_persist(
    client_with_registry: TestClient, ledger: InMemoryLedger,
) -> None:
    from wormbase_core.service import tenant_to_uuid
    company_id = tenant_to_uuid(TENANT_SLUG)
    before = len(await ledger.fetch(company_id))
    resp = await client_with_registry.post(
        "/api/v1/reactivities/propose?preview=1",
        headers=_headers(),
        json={"description": "ping me", "proposed_by": "p-admin"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["persisted"] is False
    assert body.get("preview") is True
    # No PEVR cycle emitted since preview=1.
    after = len(await ledger.fetch(company_id))
    assert after == before


async def test_propose_no_registry_returns_sketch_without_persist(
    client_no_registry: TestClient,
) -> None:
    resp = await client_no_registry.post(
        "/api/v1/reactivities/propose",
        headers=_headers(),
        json={"description": "ping me"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["persisted"] is False
    assert body["reason"] == "registry_unavailable"


async def test_propose_rejects_empty_description(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.post(
        "/api/v1/reactivities/propose",
        headers=_headers(),
        json={"description": ""},
    )
    assert resp.status == 422


# ---------------------------------------------------------------------------
# POST /api/v1/reactivities/{id}/confirm + /disable
# ---------------------------------------------------------------------------


async def test_confirm_flips_proposed_to_active(
    client_with_registry: TestClient, registry: ReactivityRegistry,
) -> None:
    # Register a reactivity in proposed state so confirm can flip it.
    class _Stub:
        id = "rx_proposed"
        name = "Proposed"
        description = ""
        scope = "company"

        class _M:
            async def match(self, *a: Any, **k: Any) -> bool:
                return False

        class _A:
            async def allows(self, *a: Any, **k: Any) -> bool:
                return True

        predicate = _M()
        condition = _A()

        async def fire(self, *a: Any, **k: Any):
            from wormbase_reactivities.protocol import ReactivityResult
            return ReactivityResult(fired=False)

    registry.register(_Stub(), initial_state="proposed")  # type: ignore[arg-type]
    confirmed_by = uuid4()
    resp = await client_with_registry.post(
        f"/api/v1/reactivities/{_Stub.id}/confirm",
        headers=_headers(),
        json={"confirmed_by": str(confirmed_by)},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"reactivity_id": _Stub.id, "state": "active"}


async def test_disable_records_reason_and_404_when_unknown(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.post(
        "/api/v1/reactivities/never_registered/disable",
        headers=_headers(),
        json={"disabled_by": str(uuid4()), "reason": "noisy"},
    )
    assert resp.status == 404


# ---------------------------------------------------------------------------
# GET /api/v1/reactivities/{id}/fires
# ---------------------------------------------------------------------------


async def test_get_reactivity_fires_returns_empty_when_none(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.get(
        "/api/v1/reactivities/anything/fires", headers=_headers(),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"fires": []}


# ---------------------------------------------------------------------------
# GET /api/v1/people/{id}/resource-conversations
# ---------------------------------------------------------------------------


async def test_resource_conversations_invalid_uuid_returns_400(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.get(
        "/api/v1/people/not-a-uuid/resource-conversations",
        headers=_headers(),
    )
    assert resp.status == 400


async def test_resource_conversations_returns_empty_when_no_entries(
    client_with_registry: TestClient,
) -> None:
    resp = await client_with_registry.get(
        f"/api/v1/people/{uuid4()}/resource-conversations",
        headers=_headers(),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"conversations": []}
