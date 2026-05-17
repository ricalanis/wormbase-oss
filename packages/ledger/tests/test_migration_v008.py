"""v008 migration — projection_external_catalog.

Wave 1 cleanup 2a: the raw SQL form at
``packages/ledger/migrations/v005_external_catalog.sql`` had no applier;
this Python migration replaces it and registers in the canonical
``MIGRATIONS`` list so the boot-time runner picks it up.

The ``projection_external_catalog`` table is the silver layer that
backs catalog-mirror drift detection. Folded from
``external_catalog_imported`` ledger entries written by the
catalog-mirror data plane; the W5a Reactivity reads the latest row per
``source_id`` and compares ``snapshot_hash`` to decide whether to emit
``external_catalog_drift_detected``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v008_external_catalog import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "source_id",
    "domain_id",
    "source_kind",
    "snapshot_hash",
    "table_count",
    "edge_count",
    "metric_count",
    "import_mode",
    "imported_at",
}


@pytest.mark.asyncio
async def test_v008_creates_projection_external_catalog_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Idempotent re-apply — must not raise.
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_external_catalog")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v008_company_and_source_indexes_present() -> None:
    """Both drift-detection (source) and tenant-scope (company) indexes exist."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_external_catalog")
        )
    names = {i["name"] for i in idxs}
    assert "idx_external_catalog_source" in names
    assert "idx_external_catalog_company" in names


def test_v008_registered_in_canonical_migrations() -> None:
    """V008ExternalCatalogMigration is in the canonical MIGRATIONS list,
    monotonic and gap-free, with no version-8 duplicates."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 8 in versions, f"expected v8 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
