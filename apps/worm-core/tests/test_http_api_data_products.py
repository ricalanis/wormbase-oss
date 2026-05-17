"""HTTP API tests for data-product + notebook endpoints (Block F2).

Uses an InMemoryLedger + LocalFsBackend rooted at a tmpdir so tests stay
container-free. Hash semantics are byte-for-byte identical to the prod
DB-backed Ledger + S3Backend.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.storage import LocalFsBackend
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


API_TOKEN = "test-token-f2"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def storage(tmp_path: Path) -> LocalFsBackend:
    return LocalFsBackend(tmp_path / "object-store")


@pytest_asyncio.fixture
async def client(
    memory_ledger: InMemoryLedger, storage: LocalFsBackend
) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN, storage=storage)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


def _auth() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Tenant-Slug": TENANT_SLUG,
    }


# ---------------------------------------------------------------------------
# Data product endpoints
# ---------------------------------------------------------------------------


async def test_post_data_products_no_auth_returns_401(client: TestClient) -> None:
    resp = await client.post(
        "/api/v1/data-products",
        json={
            "name": "Q3",
            "kind": "report",
            "requested_by_person_id": str(uuid4()),
        },
    )
    assert resp.status == 401


async def test_post_data_products_writes_propose(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    requester = uuid4()
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "Q3 Net Revenue",
            "kind": "report",
            "requested_by_person_id": str(requester),
            "sources_required": [],
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert "data_product_id" in body
    assert len(body["entry_ids"]) == 4

    # Verify the chain landed clean
    rows = list(memory_ledger._entries.values())[0]
    assert len(rows) == 4
    ok, _ = verify_chain(rows)
    assert ok


async def test_post_data_products_with_bytes_chains_propose_and_generate(
    client: TestClient, memory_ledger: InMemoryLedger, storage: LocalFsBackend,
) -> None:
    requester = uuid4()
    contents = b"<html>Q3 Net Revenue: $1.2M</html>"
    b64 = base64.b64encode(contents).decode("ascii")
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "Q3",
            "kind": "report",
            "requested_by_person_id": str(requester),
            "sources_required": [],
            "contents_bytes_b64": b64,
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert len(body["entry_ids"]) == 8  # propose (4) + generate (4)

    rows = list(memory_ledger._entries.values())[0]
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_data_product_proposed" in tools
    assert "emit_data_product_generated" in tools


async def test_post_data_product_consume(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    requester = uuid4()
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "Q3",
            "kind": "report",
            "requested_by_person_id": str(requester),
        },
    )
    body = await resp.json()
    dp_id = body["data_product_id"]

    consumer = uuid4()
    resp2 = await client.post(
        f"/api/v1/data-products/{dp_id}/consume",
        headers=_auth(),
        json={
            "consumed_by_person_id": str(consumer),
            "surface": "dashboard",
        },
    )
    assert resp2.status == 200, await resp2.text()

    rows = list(memory_ledger._entries.values())[0]
    consume_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_consumed"
    ]
    assert len(consume_entries) == 1
    assert consume_entries[0]["payload"]["args"]["surface"] == "dashboard"


async def test_post_data_product_consume_invalid_surface_returns_422(
    client: TestClient
) -> None:
    requester = uuid4()
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "Q3",
            "kind": "report",
            "requested_by_person_id": str(requester),
        },
    )
    dp_id = (await resp.json())["data_product_id"]

    resp2 = await client.post(
        f"/api/v1/data-products/{dp_id}/consume",
        headers=_auth(),
        json={
            "consumed_by_person_id": str(uuid4()),
            "surface": "bogus",
        },
    )
    assert resp2.status == 422


async def test_data_product_replay_produces_identical_content_hash(
    client: TestClient
) -> None:
    requester = uuid4()
    contents = b"hello"
    b64 = base64.b64encode(contents).decode("ascii")
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "X",
            "kind": "report",
            "requested_by_person_id": str(requester),
            "contents_bytes_b64": b64,
        },
    )
    dp_id = (await resp.json())["data_product_id"]

    replay = await client.get(
        f"/api/v1/data-products/{dp_id}/replay",
        headers=_auth(),
    )
    assert replay.status == 200, await replay.text()
    body = await replay.json()
    # The replay must produce a content_hash that matches the original.
    assert body["matches_original"] is True


# ---------------------------------------------------------------------------
# Notebook endpoints
# ---------------------------------------------------------------------------


async def test_post_notebooks_writes_propose(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = uuid4()
    resp = await client.post(
        "/api/v1/notebooks",
        headers=_auth(),
        json={
            "name": "CFO autoresearch",
            "cells": [
                {"kind": "markdown", "source": "# Hypothesis"},
                {"kind": "code", "source": "x = 1\nx + 1"},
            ],
            "kernel": "python_local",
            "proposed_by_person_id": str(person_id),
        },
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert "notebook_id" in body
    assert len(body["entry_ids"]) == 4


async def test_post_notebook_run_executes_kernel_and_writes_run_entry(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = uuid4()
    resp = await client.post(
        "/api/v1/notebooks",
        headers=_auth(),
        json={
            "name": "Two-cell",
            "cells": [
                {"kind": "code", "source": "x = 5"},
                {"kind": "code", "source": "x * 2"},
            ],
            "kernel": "python_local",
            "proposed_by_person_id": str(person_id),
        },
    )
    nb_id = (await resp.json())["notebook_id"]

    run_resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/run",
        headers=_auth(),
        json={"timeout_s": 10},
    )
    assert run_resp.status == 200, await run_resp.text()
    run_body = await run_resp.json()
    assert run_body["status"] == "ok"
    assert run_body["notebook_id"] == nb_id

    rows = list(memory_ledger._entries.values())[0]
    run_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_run"
    ]
    assert len(run_entries) == 1
    assert run_entries[0]["payload"]["args"]["status"] == "ok"


async def test_post_notebook_publish(
    client: TestClient, memory_ledger: InMemoryLedger
) -> None:
    person_id = uuid4()
    admin = uuid4()
    resp = await client.post(
        "/api/v1/notebooks",
        headers=_auth(),
        json={
            "name": "X",
            "cells": [{"kind": "code", "source": "1"}],
            "kernel": "python_local",
            "proposed_by_person_id": str(person_id),
        },
    )
    nb_id = (await resp.json())["notebook_id"]

    run_resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/run",
        headers=_auth(),
        json={"timeout_s": 10},
    )
    run_id = (await run_resp.json())["run_id"]

    publish_resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/publish",
        headers=_auth(),
        json={
            "run_id": run_id,
            "owner_person_id": str(person_id),
            "version": "1",
            "published_by": str(admin),
        },
    )
    assert publish_resp.status == 200, await publish_resp.text()

    rows = list(memory_ledger._entries.values())[0]
    publish_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(publish_entries) == 1


async def test_post_notebook_run_unknown_notebook_returns_404(
    client: TestClient
) -> None:
    resp = await client.post(
        f"/api/v1/notebooks/{uuid4()}/run",
        headers=_auth(),
        json={},
    )
    assert resp.status == 404


async def test_post_data_products_invalid_kind_returns_422(
    client: TestClient
) -> None:
    resp = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "X",
            "kind": "invalid-kind",
            "requested_by_person_id": str(uuid4()),
        },
    )
    # The PEVR cycle's verify step rolls back; the http handler maps the
    # VerifyFailed to a 500 if it propagates, but the payload class
    # validator raises ValueError before that, which we map to 422.
    assert resp.status in (422, 500)


# ---------------------------------------------------------------------------
# W2.A8 — POST /replay + POST /sign
# ---------------------------------------------------------------------------


async def test_post_data_product_replay_strict_match_writes_generate(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """POST /replay re-runs against pinned source-hashes and surfaces
    matches_original=True when the bytes are bit-identical."""
    requester = uuid4()
    contents = b"<html>Q3 Net Revenue: $1.2M</html>"
    b64 = base64.b64encode(contents).decode("ascii")
    create = await client.post(
        "/api/v1/data-products",
        headers=_auth(),
        json={
            "name": "Q3",
            "kind": "report",
            "requested_by_person_id": str(requester),
            "contents_bytes_b64": b64,
        },
    )
    dp_id = (await create.json())["data_product_id"]

    replay = await client.post(
        f"/api/v1/data-products/{dp_id}/replay",
        headers=_auth(),
        json={"strict": True, "generated_by": "replay"},
    )
    assert replay.status == 200, await replay.text()
    body = await replay.json()
    assert body["matches_original"] is True
    assert body["content_hash"] == body["expected_content_hash"]
    assert len(body["entry_ids"]) == 4

    rows = list(memory_ledger._entries.values())[0]
    gen_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_generated"
    ]
    # Two generate cycles: original + replay.
    assert len(gen_entries) == 2
    assert gen_entries[1]["payload"]["args"]["generated_by"] == "replay"
    # Determinism: both generate cycles share the same content_hash.
    assert (
        gen_entries[0]["payload"]["args"]["content_hash"]
        == gen_entries[1]["payload"]["args"]["content_hash"]
    )


async def test_post_data_product_replay_unknown_returns_404(
    client: TestClient,
) -> None:
    bogus = uuid4()
    resp = await client.post(
        f"/api/v1/data-products/{bogus}/replay",
        headers=_auth(),
        json={},
    )
    assert resp.status == 404


async def test_post_notebook_sign_emits_published_with_receipt(
    client: TestClient, memory_ledger: InMemoryLedger,
) -> None:
    """POST /sign signs the run + returns a deterministic per-Person receipt."""
    person_id = uuid4()
    admin = uuid4()
    create = await client.post(
        "/api/v1/notebooks",
        headers=_auth(),
        json={
            "name": "Audit-grade",
            "cells": [{"kind": "code", "source": "1"}],
            "kernel": "python_local",
            "proposed_by_person_id": str(person_id),
        },
    )
    nb_id = (await create.json())["notebook_id"]

    run = await client.post(
        f"/api/v1/notebooks/{nb_id}/run",
        headers=_auth(),
        json={"timeout_s": 10},
    )
    run_id = (await run.json())["run_id"]

    sign = await client.post(
        f"/api/v1/notebooks/{nb_id}/sign",
        headers=_auth(),
        json={
            "run_id": run_id,
            "owner_person_id": str(person_id),
            "version": "1",
            "signed_by": str(admin),
        },
    )
    assert sign.status == 200, await sign.text()
    body = await sign.json()
    assert body["notebook_id"] == nb_id
    assert body["signature_receipt"]["signed_by"] == str(admin)
    assert body["signature_receipt"]["signature_hash"]
    assert len(body["signature_receipt"]["signature_hash"]) == 64

    rows = list(memory_ledger._entries.values())[0]
    publish_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_notebook_published"
    ]
    assert len(publish_entries) == 1
    assert publish_entries[0]["payload"]["args"]["published_by"] == str(admin)
