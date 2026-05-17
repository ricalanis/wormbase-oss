"""POST /api/v1/write_actions/import_dbt_catalog — Wave 3.2 Hole #2 (dbt branch).

Backs the v1.1 production-hardening plan Task 2. The dashboard's
``/onboarding/connect/dbt-manifest`` form posts to this endpoint;
before v1.1 the stub branch fired with an "endpoint v1.1" error.

Coverage:
- Happy path against the vendored jaffle_shop fixture (8 edges, 8 tables).
- 404 fetch failure → 400 response.
- Unsupported manifest schema version → 400 response.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-dbt-catalog"
TENANT_SLUG = "baseworm"

# The fixture lives in the catalog-mirror package; we resolve the path
# relative to the repo root so the test stays insensitive to where
# pytest is launched from.
FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "wormbase-catalog-mirror"
    / "tests"
    / "fixtures"
    / "jaffle_shop_manifest.json"
)


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


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


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


async def test_import_dbt_catalog_emits_external_catalog_imported_plus_lineage(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """Happy path: jaffle_shop manifest → 1 catalog import + 1 lineage entry (8 edges)."""
    assert FIXTURE.exists(), f"missing fixture at {FIXTURE}"
    domain_id = uuid4()
    admin_id = uuid4()

    resp = await client.post(
        "/api/v1/write_actions/import_dbt_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "manifest_uri": f"file://{FIXTURE}",
            "domain_id": str(domain_id),
            "imported_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert UUID(body["source_id"])
    assert body["source_id"] == body["sourceId"]

    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [r["payload"]["tool"] for r in execute_rows]
    # jaffle_shop carries no semantic-layer metrics, so the chain is
    # external_catalog_imported + 8 catalog_table_imported (Wave 2 Sub-wave B
    # per-table substrate) + one external_lineage_imported carrying all
    # 8 edges.
    assert tools[0] == "emit_external_catalog_imported"
    # Per-table entries arrive between the catalog summary and the
    # lineage edge entry (matches _emit_external_catalog_pevr order).
    catalog_table_tools = [
        t for t in tools if t == "emit_catalog_table_imported"
    ]
    assert len(catalog_table_tools) == 8
    assert "emit_external_lineage_imported" in tools
    # No metric companions for jaffle_shop in v12.
    assert all(t != "emit_external_metric_imported" for t in tools)

    primary_args = execute_rows[0]["payload"]["args"]
    assert primary_args["source_kind"] == "dbt"
    assert primary_args["import_mode"] == "initial"
    assert primary_args["edge_count"] == 8
    assert primary_args["table_count"] == 8
    assert primary_args["domain_id"] == str(domain_id)

    # Lineage entry — locate by tool name (no longer position-pinned).
    lineage_rows = [
        r for r in execute_rows
        if r["payload"]["tool"] == "emit_external_lineage_imported"
    ]
    assert len(lineage_rows) == 1
    lineage_args = lineage_rows[0]["payload"]["args"]
    # external_lineage_imported carries the flat edge list (one entry
    # per import — matches CatalogImportReactivity.fire shape).
    assert len(lineage_args["edges"]) == 8

    # Per-table substrate: every catalog_table_imported entry carries the
    # snapshot_hash from the primary catalog summary, plus a table_id +
    # columns tuple. jaffle_shop populates columns (dbt manifest carries
    # per-column type info).
    snapshot_hash = primary_args["snapshot_hash"]
    table_imported_rows = [
        r for r in execute_rows
        if r["payload"]["tool"] == "emit_catalog_table_imported"
    ]
    assert all(
        r["payload"]["args"]["snapshot_hash"] == snapshot_hash
        for r in table_imported_rows
    )
    # At least one table should have populated columns (jaffle_shop dbt
    # manifest includes column-level metadata for the staging models).
    populated = [
        r for r in table_imported_rows
        if r["payload"]["args"].get("columns")
    ]
    assert populated, "expected at least one catalog_table_imported entry to carry columns"


async def test_import_dbt_catalog_missing_file_returns_400(
    client: TestClient,
) -> None:
    """A non-existent local manifest path → 400, not 500."""
    resp = await client.post(
        "/api/v1/write_actions/import_dbt_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "manifest_uri": "file:///definitely/not/a/real/path/manifest.json",
            "domain_id": str(uuid4()),
            "imported_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()


async def test_import_dbt_catalog_unsupported_schema_returns_400(
    client: TestClient, tmp_path: Path,
) -> None:
    """A manifest with an unsupported schema version → 400."""
    fake = tmp_path / "fake_manifest.json"
    fake.write_text(json.dumps({
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v3.json",
        },
        "nodes": {},
        "metrics": {},
    }))

    resp = await client.post(
        "/api/v1/write_actions/import_dbt_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "manifest_uri": f"file://{fake}",
            "domain_id": str(uuid4()),
            "imported_by": str(uuid4()),
        },
    )
    assert resp.status == 400, await resp.text()
    text = await resp.text()
    # Surface should mention the manifest schema problem so the form
    # renders an actionable error inline.
    assert "schema" in text.lower() or "manifest" in text.lower()
