"""Unit tests for the connector registry HTTP endpoints (W2.A5).

Covers:
- GET /api/v1/connectors → catalog payload (kind, status, capabilities,
  config_schema, classification_hints) — no auth required.
- POST /api/v1/connectors/{kind}/test → real Connector.authenticate
  invocation. Bearer-auth required. Honest failures surface the
  upstream error message verbatim; coming_soon kinds 409.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-token-connectors"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[TestClient]:
    app = build_app(ledger=InMemoryLedger(), api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


async def test_get_connectors_returns_kinds_payload(client: TestClient) -> None:
    """The list endpoint exposes every registered connector with status."""
    resp = await client.get("/api/v1/connectors")
    assert resp.status == 200
    body = await resp.json()
    assert "kinds" in body
    kinds = body["kinds"]
    assert isinstance(kinds, list)
    assert len(kinds) >= 11, f"expected ≥11 day-one connectors, got {len(kinds)}"

    # Every entry has the expected shape.
    for entry in kinds:
        assert "kind" in entry
        assert "label" in entry
        assert "status" in entry
        assert entry["status"] in ("production", "preview", "coming_soon")
        assert "capabilities" in entry
        assert isinstance(entry["capabilities"], list)
        assert "config_schema" in entry
        assert isinstance(entry["config_schema"], list)
        assert "classification_hints" in entry
        assert isinstance(entry["classification_hints"], list)
        assert "status_note" in entry

    # Postgres is registered and production-grade.
    by_kind = {e["kind"]: e for e in kinds}
    assert "postgres" in by_kind
    assert by_kind["postgres"]["status"] == "production"
    assert any(f["name"] == "dsn" for f in by_kind["postgres"]["config_schema"])


async def test_get_connectors_no_auth_required(client: TestClient) -> None:
    """The list endpoint is read-only and unauthenticated like /mcp/catalog."""
    resp = await client.get("/api/v1/connectors")
    assert resp.status == 200


async def test_post_connector_test_requires_auth(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/connectors/postgres/test",
        json={"config": {"dsn": "postgres://x:y@nope/db"}},
    )
    assert resp.status == 401


async def test_post_connector_test_unknown_kind_returns_404(
    client: TestClient,
) -> None:
    resp = await client.post(
        "/api/v1/connectors/madeupkind/test",
        headers=_auth_headers(),
        json={"config": {}},
    )
    assert resp.status == 404
    body = await resp.json()
    assert body["ok"] is False
    assert "unknown" in body["error"].lower()


async def test_post_connector_test_coming_soon_returns_409(
    client: TestClient,
) -> None:
    """coming_soon connectors must not run authenticate."""
    resp = await client.post(
        "/api/v1/connectors/bigquery/test",
        headers=_auth_headers(),
        json={"config": {"project_id": "x", "service_account_json": "{}"}},
    )
    assert resp.status == 409
    body = await resp.json()
    assert body["ok"] is False
    assert "coming_soon" in body["error"]


async def test_post_connector_test_returns_hash_receipt_on_success(
    client: TestClient, tmp_path,
) -> None:
    """csv_local.authenticate succeeds for any non-empty path; returns hash."""
    target = tmp_path / "fake.csv"
    target.write_text("a,b\n1,2\n")
    resp = await client.post(
        "/api/v1/connectors/csv_local/test",
        headers=_auth_headers(),
        json={"config": {"path": str(target)}},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["kind"] == "csv_local"
    assert "hash" in body
    assert len(body["hash"]) == 12


async def test_post_connector_test_failure_surfaces_validation_error(
    client: TestClient,
) -> None:
    """Missing required field surfaces the connector's ValueError verbatim."""
    resp = await client.post(
        "/api/v1/connectors/csv_local/test",
        headers=_auth_headers(),
        json={"config": {}},  # missing 'path'
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is False
    assert "path" in body["error"].lower()
