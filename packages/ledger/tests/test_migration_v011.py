"""v011 migration — projection_external_metric.

Wave 1 cleanup 2a: the raw SQL form at
``packages/ledger/migrations/v008_external_metric.sql`` had no applier;
this Python migration replaces it and registers in the canonical
``MIGRATIONS`` list so the boot-time runner picks it up.

One row per imported semantic-layer metric definition (normalized
across dbt MetricFlow / Cube / Malloy / LookML), folded from
``external_metric_imported`` ledger entries. ``expression`` /
``time_grain`` / ``description`` are nullable — upstream catalogs
differ on which fields they expose.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v011_external_metric import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "source_id",
    "name",
    "expression",
    "time_grain",
    "dimensions",
    "description",
    "imported_at",
}


@pytest.mark.asyncio
async def test_v011_creates_projection_external_metric_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_external_metric")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v011_optional_fields_are_nullable() -> None:
    """expression / time_grain / description are nullable — upstream
    catalogs differ on which fields they expose, and the data plane
    should not drop a metric just because one optional field is missing."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]: c
                for c in inspect(sc).get_columns("projection_external_metric")
            }
        )
    for nullable_col in ("expression", "time_grain", "description"):
        assert cols[nullable_col]["nullable"] is True, (
            f"{nullable_col} must be nullable so partial-coverage upstreams "
            "don't drop the row"
        )


@pytest.mark.asyncio
async def test_v011_unique_source_name_index_present() -> None:
    """One row per (source_id, name) — enforced by unique index."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_external_metric")
        )
    by_name = {i["name"]: i for i in idxs}
    assert "uq_external_metric_source_name" in by_name
    # SQLite reflects unique-index flag as ``1`` / ``0``; Postgres as
    # ``True`` / ``False``. Truthy check works on both backends.
    assert by_name["uq_external_metric_source_name"]["unique"]
    assert "idx_external_metric_company" in by_name


def test_v011_registered_in_canonical_migrations() -> None:
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 11 in versions, f"expected v11 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
