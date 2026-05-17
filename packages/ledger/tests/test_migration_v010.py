"""v010 migration — projection_external_policy.

Wave 1 cleanup 2a: the raw SQL form at
``packages/ledger/migrations/v007_external_policy.sql`` had no applier;
this Python migration replaces it and registers in the canonical
``MIGRATIONS`` list so the boot-time runner picks it up.

S2 spike finding: ``body`` MUST stay nullable. Snowflake catalog roles
typically have SHOW privileges on policies but not APPLY, so the
policy SQL body is unreachable on read-only catalog credentials.
Drift on policy existence still works without it; any NOT NULL
constraint here would break the catalog-mirror Reactivity on
read-only roles. The Python migration preserves this invariant.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v010_external_policy import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "source_id",
    "policy_fqn",
    "policy_kind",
    "body",
    "applied_to",
    "imported_at",
}


@pytest.mark.asyncio
async def test_v010_creates_projection_external_policy_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_external_policy")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v010_body_is_nullable() -> None:
    """S2 finding: catalog roles without APPLY can't fetch policy SQL.
    body MUST be nullable, or the catalog-mirror Reactivity breaks on
    read-only Snowflake roles."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]: c
                for c in inspect(sc).get_columns("projection_external_policy")
            }
        )
    assert cols["body"]["nullable"] is True, (
        "body MUST stay nullable — S2 spike finding"
    )


@pytest.mark.asyncio
async def test_v010_unique_source_fqn_index_present() -> None:
    """One row per (source_id, policy_fqn) — enforced by unique index."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: inspect(sc).get_indexes("projection_external_policy")
        )
    by_name = {i["name"]: i for i in idxs}
    assert "uq_external_policy_source_fqn" in by_name
    # SQLite reflects unique-index flag as ``1`` / ``0``; Postgres as
    # ``True`` / ``False``. Truthy check works on both backends.
    assert by_name["uq_external_policy_source_fqn"]["unique"]
    assert "idx_external_policy_company" in by_name


def test_v010_registered_in_canonical_migrations() -> None:
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 10 in versions, f"expected v10 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
