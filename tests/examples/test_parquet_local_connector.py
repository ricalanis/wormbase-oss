"""Conformance test for the reference parquet_local connector.

Asserts the reference passes all six W6.A4 invariants — the same
suite a third-party Connector author would run against their own
class via ``wormbase-tools-test``. We invoke the public assertions
directly (rather than the pytest plugin) so this test runs in CI
even when the harness package isn't installed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from examples.connectors.parquet_local import (
    AuthHandle,
    Change,
    ParquetLocalConnector,
    Profile,
    ResourceProposal,
    SecretBundle,
)


@pytest.fixture
def parquet_path(tmp_path: Path) -> str:
    p = tmp_path / "fixture.parquet"
    table = pa.table(
        {
            "id": [1, 2, 3, 4, 5],
            "name": ["Alice", "Bob", "Carol", "Dan", "Eve"],
            "amount": [10.5, 20.0, 30.25, 40.0, 50.75],
        }
    )
    pq.write_table(table, p)
    return str(p)


# ---------------------------------------------------------------------------
# Six invariants — one test per invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_valid_returns_authhandle(parquet_path: str) -> None:
    c = ParquetLocalConnector()
    handle = await c.authenticate(SecretBundle({"path": parquet_path}))
    assert isinstance(handle, AuthHandle)
    assert handle.connector_kind == "parquet_local"
    assert handle.handle_id == parquet_path
    assert handle.extra["path"] == parquet_path


@pytest.mark.asyncio
async def test_authenticate_invalid_raises() -> None:
    c = ParquetLocalConnector()
    with pytest.raises(ValueError, match="path"):
        await c.authenticate(SecretBundle({}))


@pytest.mark.asyncio
async def test_discover_stable_ordering(parquet_path: str) -> None:
    c = ParquetLocalConnector()
    handle = await c.authenticate(SecretBundle({"path": parquet_path}))
    first = await c.discover(handle)
    second = await c.discover(handle)
    assert isinstance(first, list)
    assert len(first) == 1
    assert isinstance(first[0], ResourceProposal)
    assert first[0].kind == "file"
    assert first[0].metadata["mimetype"] == "application/x-parquet"
    # Stable ordering: same (kind, resource_id) tuples in same order.
    assert [(r.kind, r.resource_id) for r in first] == [
        (r.kind, r.resource_id) for r in second
    ]


@pytest.mark.asyncio
async def test_profile_idempotent(parquet_path: str) -> None:
    c = ParquetLocalConnector()
    handle = await c.authenticate(SecretBundle({"path": parquet_path}))
    first = await c.profile(handle, parquet_path)
    second = await c.profile(handle, parquet_path)
    assert isinstance(first, Profile)
    assert first.row_count == 5
    assert first.column_count == 3
    assert {col["name"] for col in first.columns} == {"id", "name", "amount"}
    assert first.schema_hash == second.schema_hash
    assert first.columns == second.columns


@pytest.mark.asyncio
async def test_sample_deterministic(parquet_path: str) -> None:
    c = ParquetLocalConnector()
    handle = await c.authenticate(SecretBundle({"path": parquet_path}))
    n = 64
    first = await c.sample(handle, parquet_path, n)
    second = await c.sample(handle, parquet_path, n)
    assert isinstance(first, bytes)
    assert isinstance(second, bytes)
    assert first == second
    # parquet_local treats n as a strict byte cap.
    assert len(first) <= n


@pytest.mark.asyncio
async def test_watch_async_iterator_drains_cleanly(parquet_path: str) -> None:
    c = ParquetLocalConnector()
    handle = await c.authenticate(SecretBundle({"path": parquet_path}))
    iterator = c.watch(handle, parquet_path)
    # parquet_local is pull-only; it yields nothing.
    count = 0
    async for _change in iterator:
        count += 1
        if count >= 5:
            break
    assert count == 0


# ---------------------------------------------------------------------------
# Bonus: end-to-end via the wormbase_tools_test public API (when available)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_conformance_via_public_api(parquet_path: str) -> None:
    """Run all six invariants through the harness's public API.

    Skipped if ``wormbase_tools_test`` isn't installed in the active
    venv; the unit tests above cover every invariant directly.
    """
    pytest.importorskip("wormbase_tools_test")
    from wormbase_tools_test import run_full_conformance

    c = ParquetLocalConnector()
    results = await run_full_conformance(
        c,
        valid_secrets=SecretBundle({"path": parquet_path}),
        invalid_secrets=SecretBundle({}),
        known_resource_id=parquet_path,
        sample_n=64,
        byte_cap_strict=True,
    )
    assert all(v == "pass" for v in results.values())
    assert len(results) == 6
