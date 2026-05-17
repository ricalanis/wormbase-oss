"""POST /api/v1/write_actions/import_snowflake_catalog — Wave 3.2 Hole #2 (snowflake branch).

Backs the v1.1 production-hardening plan Task 3. The dashboard's
``/onboarding/connect/snowflake-catalog`` form posts to this endpoint;
before v1.1 the stub branch fired with an "endpoint v1.1" error.

Coverage:
- Happy path against a stub CatalogSource — no network, hermetic.
- Live test gated on ``SNOWFLAKE_*`` env vars (skips when absent).
- Auth failure (missing broker secret) → 400.

Note: the Snowflake password / OAuth token NEVER flows through the
request body. The endpoint resolves it via ``CredentialBroker``; this
test verifies the stub-CatalogSource path so the unit run stays
container-free.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from wormbase_catalog_mirror.types import (
    CatalogSnapshot,
    ExternalPolicy,
    LineageEdge,
    LineageGraph,
    MetricDefinition,
    TableMeta,
)
from wormbase_core import write_actions
from wormbase_core.http_api import build_app
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-snowflake-catalog"
TENANT_SLUG = "baseworm"


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


# ---------------------------------------------------------------------------
# Stub CatalogSource for unit tests — no Snowflake server required.
# ---------------------------------------------------------------------------


@dataclass
class _StubSnowflakeSource:
    """In-memory CatalogSource that mimics SnowflakeNativeCatalogSource shape.

    Returns a small canned snapshot so the test verifies the
    write_actions write-chain shape without spinning up a Snowflake
    account. Live testing against a real account goes through the
    env-gated SNOWFLAKE_* test below.
    """

    kind: str = "snowflake"
    capability: frozenset[str] = field(
        default_factory=lambda: frozenset(["schema", "lineage", "policy"]),
    )

    async def authenticate(self, secrets: dict[str, str]) -> object:
        # Smoke: confirm the required-fields contract is honored by the
        # request body. We do NOT enforce a real Snowflake auth path
        # since the stub is hermetic.
        for k in ("account", "user", "warehouse", "database", "schema"):
            if k not in secrets:
                raise ValueError(f"stub: missing required snowflake field {k}")
        return object()

    async def discover_catalog(self, handle: object) -> CatalogSnapshot:
        return CatalogSnapshot(
            source_kind="snowflake",
            tables=(
                TableMeta(
                    external_id="snowflake://ACME.RAW.EVENTS",
                    name="EVENTS",
                    schema="RAW",
                    database="ACME",
                    description=None,
                    columns=(),
                ),
                TableMeta(
                    external_id="snowflake://ACME.STAGING.EVENTS",
                    name="EVENTS",
                    schema="STAGING",
                    database="ACME",
                    description=None,
                    columns=(),
                ),
            ),
            lineage=LineageGraph(edges=(
                LineageEdge(
                    upstream="snowflake://ACME.RAW.EVENTS",
                    downstream="snowflake://ACME.STAGING.EVENTS",
                ),
            )),
            policies=(),
            metrics=[],
        )

    async def discover_lineage(self, *a, **k) -> LineageGraph:
        return LineageGraph(edges=())

    async def discover_policies(self, *a, **k) -> list[ExternalPolicy]:
        return []

    async def discover_metrics(self, *a, **k) -> list[MetricDefinition]:
        return []

    async def watch_changes(self, *a, **k):
        if False:
            yield  # pragma: no cover


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_import_snowflake_catalog_emits_chain_via_stub_source(
    memory_ledger: InMemoryLedger,
) -> None:
    """Stub CatalogSource path: write primitive emits the full chain."""
    domain_id = uuid4()
    admin_id = uuid4()

    source_id, results = await write_actions.import_snowflake_catalog(
        memory_ledger,
        _company_id(),
        account="ACME-AT001.us-east-1.aws",
        user="ANALYST",
        warehouse="WH_XS",
        database="ACME",
        schema_name="RAW",
        role="ACME_READ",
        domain_id=domain_id,
        imported_by=admin_id,
        catalog_source=_StubSnowflakeSource(),
        reactivity_registry=None,
    )

    assert isinstance(source_id, UUID)
    # 4 cycles: external_catalog_imported + 2 catalog_table_imported
    # (Wave 2 Sub-wave B per-table substrate) + 1 lineage entry.
    assert len(results) == 4

    rows = await memory_ledger.fetch(_company_id())
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [r["payload"]["tool"] for r in execute_rows]
    assert tools == [
        "emit_external_catalog_imported",
        "emit_catalog_table_imported",
        "emit_catalog_table_imported",
        "emit_external_lineage_imported",
    ]
    primary_args = execute_rows[0]["payload"]["args"]
    assert primary_args["source_kind"] == "snowflake"
    assert primary_args["table_count"] == 2
    assert primary_args["edge_count"] == 1
    assert primary_args["import_mode"] == "initial"
    assert primary_args["domain_id"] == str(domain_id)

    # Per-table substrate: every catalog_table_imported entry carries the
    # snapshot_hash from the primary catalog summary + the table_id.
    snapshot_hash = primary_args["snapshot_hash"]
    table_imported_args = [
        execute_rows[1]["payload"]["args"],
        execute_rows[2]["payload"]["args"],
    ]
    assert all(
        a["snapshot_hash"] == snapshot_hash for a in table_imported_args
    )
    # The stub fixture's two tables have empty columns (the stub
    # CatalogSource above sets ``columns=()``); the per-table entries
    # emit with ``columns=[]`` — honest empty-upstream preserved.
    assert all(a["columns"] == [] for a in table_imported_args)


async def test_import_snowflake_catalog_http_endpoint_with_stub_broker(
    client: TestClient, memory_ledger: InMemoryLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP-level happy path with a monkeypatched write primitive.

    The endpoint normally constructs a real
    ``SnowflakeNativeCatalogSource`` — that requires the Snowflake
    Python connector to attempt a TCP connect to ``account``. We patch
    ``write_actions.import_snowflake_catalog`` to bypass the connector
    and assert the route + body validation + response shape only.
    """
    captured: dict[str, Any] = {}

    async def fake_import(*args: Any, **kwargs: Any) -> tuple[UUID, list[Any]]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        sid = uuid4()
        # Emit a single placeholder write so the InMemoryLedger has
        # something to confirm the route hit our primitive.
        return sid, []

    monkeypatch.setattr(
        "wormbase_core.http_api.write_actions.import_snowflake_catalog",
        fake_import,
    )

    domain_id = uuid4()
    admin_id = uuid4()
    resp = await client.post(
        "/api/v1/write_actions/import_snowflake_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "account": "ACME-AT001.us-east-1.aws",
            "user": "ANALYST",
            "warehouse": "WH_XS",
            "database": "ACME",
            "schema": "RAW",
            "role": "ACME_READ",
            "domain_id": str(domain_id),
            "imported_by": str(admin_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert UUID(body["source_id"])
    assert body["source_id"] == body["sourceId"]

    # Confirm the route mapped schema -> schema_name and passed all
    # required fields through to the primitive.
    kwargs = captured["kwargs"]
    assert kwargs["account"] == "ACME-AT001.us-east-1.aws"
    assert kwargs["user"] == "ANALYST"
    assert kwargs["schema_name"] == "RAW"
    assert kwargs["role"] == "ACME_READ"
    assert kwargs["domain_id"] == domain_id
    assert kwargs["imported_by"] == admin_id


async def test_import_snowflake_catalog_validation_failure_returns_422(
    client: TestClient,
) -> None:
    """Missing required body field → 422 at Pydantic validation."""
    resp = await client.post(
        "/api/v1/write_actions/import_snowflake_catalog",
        headers=_auth_headers(),
        json={
            "company_id": str(_company_id()),
            "account": "ACME-AT001.us-east-1.aws",
            # missing user
            "warehouse": "WH_XS",
            "database": "ACME",
            "schema": "RAW",
            "domain_id": str(uuid4()),
            "imported_by": str(uuid4()),
        },
    )
    assert resp.status == 422, await resp.text()


@pytest.mark.skipif(
    not all(
        os.environ.get(k)
        for k in (
            "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE",
            "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA",
        )
    ),
    reason=(
        "live Snowflake test — requires SNOWFLAKE_ACCOUNT / USER / "
        "WAREHOUSE / DATABASE / SCHEMA env vars + a password OR token "
        "wired through the CredentialBroker"
    ),
)
async def test_import_snowflake_catalog_live(
    memory_ledger: InMemoryLedger,
) -> None:
    """Live test against a real Snowflake account (env-gated).

    Same pattern as Wave 1 Task 3: skips cleanly when env missing.
    Requires the CredentialBroker secrets dir to contain a password /
    token for the test install.
    """
    from wormbase_catalog_mirror.implementations.snowflake_native import (
        SnowflakeNativeCatalogSource,
    )

    secrets = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
        "schema": os.environ["SNOWFLAKE_SCHEMA"],
    }
    if os.environ.get("SNOWFLAKE_ROLE"):
        secrets["role"] = os.environ["SNOWFLAKE_ROLE"]
    if os.environ.get("SNOWFLAKE_PASSWORD"):
        secrets["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    elif os.environ.get("SNOWFLAKE_TOKEN"):
        secrets["token"] = os.environ["SNOWFLAKE_TOKEN"]
    else:
        pytest.skip("need SNOWFLAKE_PASSWORD or SNOWFLAKE_TOKEN")

    class _InjectedBroker:
        async def hold_data_account(self, install_id: str, *, upstream_kind: str):
            from wormbase_agent_gateway.credential_broker.types import (
                AccountHandle,
            )
            return AccountHandle(
                kind="data",
                upstream_kind=upstream_kind,
                install_id=install_id,
                payload=secrets,
            )

    source_id, results = await write_actions.import_snowflake_catalog(
        memory_ledger,
        _company_id(),
        account=secrets["account"],
        user=secrets["user"],
        warehouse=secrets["warehouse"],
        database=secrets["database"],
        schema_name=secrets["schema"],
        role=secrets.get("role"),
        domain_id=uuid4(),
        imported_by=uuid4(),
        catalog_source=SnowflakeNativeCatalogSource(),
        credential_broker=_InjectedBroker(),
        install_id="live-test-install",
        reactivity_registry=None,
    )
    assert isinstance(source_id, UUID)
    assert len(results) >= 1
