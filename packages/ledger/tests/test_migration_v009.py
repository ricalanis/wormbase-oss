"""v009 migration — projection_external_lineage.

Wave 1 cleanup 2a: the raw SQL form at
``packages/ledger/migrations/v006_external_lineage.sql`` had no applier;
this Python migration replaces it and registers in the canonical
``MIGRATIONS`` list so the boot-time runner picks it up.

One row per upstream lineage edge per snapshot import; folded from
``external_lineage_imported`` ledger entries. Both upstream- and
downstream-keyed indexes are present so impact-of-upstream-change vs.
provenance-of-downstream-asset both render cheaply.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v009_external_lineage import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "source_id",
    "upstream",
    "downstream",
    "imported_at",
}


@pytest.mark.asyncio
async def test_v009_creates_projection_external_lineage_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_external_lineage")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v009_bidirectional_indexes_present() -> None:
    """Upstream / downstream / source indexes all present for cheap edge lookup."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_external_lineage")
        )
    names = {i["name"] for i in idxs}
    assert "idx_external_lineage_upstream" in names
    assert "idx_external_lineage_downstream" in names
    assert "idx_external_lineage_source" in names


def test_v009_registered_in_canonical_migrations() -> None:
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 9 in versions, f"expected v9 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
