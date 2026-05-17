"""v013 migration — projection_agent_grants.

Semantic Layer Wave 2 Task 1: per-agent grants for data + model access,
status-field consolidated per Addendum 3.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v013_projection_agent_grants import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "agent_id",
    "grant_kind",
    "grant_target",
    "status",
    "granted_by",
    "granted_at",
    "budget_remaining_usd",
}


@pytest.mark.asyncio
async def test_v013_creates_projection_agent_grants_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_agent_grants")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v013_unique_triple_constraint() -> None:
    """UNIQUE on (agent_id, grant_kind, grant_target) prevents duplicate grants."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_agent_grants "
                "(id, company_id, agent_id, grant_kind, grant_target, status, "
                " granted_by, granted_at) "
                "VALUES ('g1', 'co1', 'a1', 'domain.read', 'd1', 'active', "
                "'admin', '2026-05-11T00:00:00Z')"
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_agent_grants "
                    "(id, company_id, agent_id, grant_kind, grant_target, status, "
                    " granted_by, granted_at) "
                    "VALUES ('g2', 'co1', 'a1', 'domain.read', 'd1', 'active', "
                    "'admin', '2026-05-11T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v013_grant_kind_check_constraint() -> None:
    """CHECK on grant_kind rejects unknown values."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_agent_grants "
                    "(id, company_id, agent_id, grant_kind, grant_target, status, "
                    " granted_by, granted_at) "
                    "VALUES ('g1', 'co1', 'a1', 'bogus.grant', 'd1', 'active', "
                    "'admin', '2026-05-11T00:00:00Z')"
                )
            )


def test_v013_registered_in_canonical_migrations() -> None:
    """V013 lives in MIGRATIONS, monotonic and gap-free."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 13 in versions, f"expected v13 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
