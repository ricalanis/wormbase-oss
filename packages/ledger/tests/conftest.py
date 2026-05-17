"""Pytest fixtures for wormbase-ledger.

Default backend: SQLite (aiosqlite) — fast, offline, deterministic.
Override with WORMBASE_TEST_DB_URL=postgresql+asyncpg://... to use Postgres
for the determinism gate (Task 12) when a Postgres instance is available.

Each test gets a freshly created DB file (per-test isolation), so seq counters
and chain heads start from zero.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

# We import metadata lazily inside the fixture so tests can be collected
# even when schema.py is mid-bootstrap (Task 2 vs Task 3 ordering).


@pytest.fixture(scope="function")
def test_database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    override = os.environ.get("WORMBASE_TEST_DB_URL")
    if override:
        return override
    # SQLite file per-test for isolation. We use a stable named temp dir
    # and a unique filename per fixture invocation.
    d: Path = tmp_path_factory.mktemp("wormbase-ledger-db")
    db_file = d / f"ledger_{uuid.uuid4().hex}.sqlite"
    return f"sqlite+aiosqlite:///{db_file}"


@pytest_asyncio.fixture(autouse=True)
async def _reset_schema(test_database_url: str) -> AsyncIterator[None]:
    """Drop and recreate the schema before each test."""
    from wormbase_ledger.schema import metadata

    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    yield
    await engine.dispose()
