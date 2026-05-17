"""Chaos: S3 / LocalStack returns a connection error on put_object during replay.

Failure mode
------------
The data-product replay path (POST /api/v1/data-products/{id}/replay)
needs to write the replayed bytes back to the object store before the
PEVR ``data_product_generated`` cycle lands. When the S3 backend
(LocalStack in dev, real S3 in prod) is unreachable, ``ObjectStore.put``
raises a ConnectionError-shaped exception.

Invariants the system MUST preserve
-----------------------------------
1. The orchestrator surfaces the failure to the dashboard as a 5xx
   (we accept any 500-level status code that names the error). It
   does NOT silently swallow nor return a fake success.
2. NO half-state leaks past the failure: no ``data_product_generated``
   PEVR cycle is written for the replay attempt, the replay PEVR is
   never partial (no propose without verify, no verify without
   resolve). The ledger contents are unchanged from before the failed
   replay.
3. The original artifact remains readable from the object store — we
   never overwrite the source-of-truth bytes during a failed replay.
4. Rate-limit / budget counters (the ledger's PEVR audit is the
   single source of truth here) are not corrupted. The ledger tail
   hash chain still verifies clean.

Failure-injection point
-----------------------
We patch ``LocalFsBackend.put`` (the dev-time stand-in for S3) on the
running app's storage to raise ``ConnectionError``. This is the same
error shape ``aioboto3``'s S3Backend raises when LocalStack is gone.
The handler at ``post_data_product_replay`` calls ``storage.put``
inline; we exercise the production path top to bottom.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import APP_STORAGE_KEY, build_app
from wormbase_core.storage import LocalFsBackend
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


API_TOKEN = "chaos-s3-token"
TENANT_SLUG = "baseworm"


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def storage(tmp_path: Path) -> LocalFsBackend:
    return LocalFsBackend(tmp_path / "object-store")


@pytest_asyncio.fixture
async def client(
    memory_ledger: InMemoryLedger, storage: LocalFsBackend,
) -> AsyncIterator[TestClient]:
    app = build_app(
        ledger=memory_ledger, api_token=API_TOKEN, storage=storage,
    )
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
# Test
# ---------------------------------------------------------------------------


async def test_s3_down_during_replay_surfaces_error_no_half_state(
    client: TestClient,
    memory_ledger: InMemoryLedger,
    storage: LocalFsBackend,
) -> None:
    """Replay against a dead S3: 5xx surfaces, no ledger half-state, original
    artifact unchanged."""
    requester = uuid4()
    contents = b"<html>Q3 Net Revenue: $1.2M</html>"
    b64 = base64.b64encode(contents).decode("ascii")

    # 1. Create the data product. The storage backend is healthy here.
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
    assert create.status in (200, 201), await create.text()
    dp_id = (await create.json())["data_product_id"]

    # The original artifact landed in the store.
    rows_pre_replay = list(memory_ledger._entries.values())[0]
    rows_pre_replay = list(rows_pre_replay)  # snapshot
    pre_count = len(rows_pre_replay)
    pre_hash_chain_ok, _ = verify_chain(rows_pre_replay)
    assert pre_hash_chain_ok, "ledger hash chain must be clean pre-failure"

    # Snapshot the original artifact path so we can prove it didn't
    # get overwritten by the failed replay.
    exec_rows = [r for r in rows_pre_replay if r["kind"] == "execute"]
    gen_args = next(
        r["payload"]["args"] for r in exec_rows
        if r["payload"].get("tool") == "emit_data_product_generated"
    )
    original_uri = gen_args["contents_uri"]
    original_hash = gen_args["content_hash"]
    # Verify the original is readable and its bytes match the recorded hash.
    original_bytes = await storage.get(original_uri)
    assert original_bytes == contents

    # 2. Inject the failure on storage.put — every replay attempt now
    # raises ConnectionError, mirroring "LocalStack is gone".
    app = client.server.app
    broken_storage = storage  # alias for readability
    broken_storage.put = AsyncMock(  # type: ignore[method-assign]
        side_effect=ConnectionError(
            "could not connect to s3 endpoint http://localstack:4566",
        ),
    )
    # Sanity: the app's storage handle is the same object we just patched.
    assert app[APP_STORAGE_KEY] is broken_storage

    # 3. Drive the replay. We accept any 5xx (the aiohttp handler does
    # not catch ConnectionError today; the aiohttp test runner surfaces
    # it as a 500). The user-visible invariant is: the dashboard sees
    # an error, not a silent success.
    replay_resp_status: int | None = None
    replay_resp_body: str = ""
    try:
        replay = await client.post(
            f"/api/v1/data-products/{dp_id}/replay",
            headers=_auth(),
            json={"strict": True, "generated_by": "replay"},
        )
        replay_resp_status = replay.status
        replay_resp_body = await replay.text()
    except ConnectionError as exc:
        # Some aiohttp test runners propagate the exception directly
        # rather than mapping to a 500. Either shape is honest — both
        # produce a dashboard-visible error.
        replay_resp_status = 500
        replay_resp_body = str(exc)

    # Invariant 1: a 5xx (or a propagated ConnectionError) surfaces.
    # The dashboard's /data-products tab renders the error rather than
    # a fake "Replay succeeded" badge.
    assert replay_resp_status is not None and replay_resp_status >= 500, (
        f"expected 5xx or propagated error; got {replay_resp_status} "
        f"body={replay_resp_body[:200]}"
    )

    # Invariant 2: NO new ledger rows landed for the failed replay.
    # The replay handler reads the artifact (storage.get → ok), then
    # calls storage.put → ConnectionError → never invokes
    # data_product_actions.replay_data_product. Zero PEVR delta.
    rows_post_replay = list(memory_ledger._entries.values())[0]
    assert len(rows_post_replay) == pre_count, (
        "no half-state — failed S3 put must NOT leave a partial "
        f"data_product_generated PEVR cycle; delta="
        f"{len(rows_post_replay) - pre_count}"
    )

    # Invariant 4: the hash chain is still clean.
    post_hash_chain_ok, broken = verify_chain(rows_post_replay)
    assert post_hash_chain_ok, (
        f"hash chain must remain clean after a failed replay; "
        f"broken at seq={broken}"
    )

    # Invariant 3: the original artifact bytes are unchanged. Restore
    # the storage put so we can re-read; the get path was never broken.
    re_read_bytes = await storage.get(original_uri)
    assert re_read_bytes == contents, (
        "the original artifact bytes must NOT be overwritten or "
        "corrupted by a failed replay"
    )
    # Hash unchanged.
    import hashlib
    assert hashlib.sha256(re_read_bytes).hexdigest() == original_hash
