"""v012 migration — projection_agents.

Semantic Layer Wave 2 Task 1: creates the Person sub-type table for
external + internal agents. Folded from ``agent_registered`` ledger
entries; the agent-gateway ``register_agent`` flow writes one row per
registered agent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v012_projection_agents import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "person_id",
    "external_provider",
    "display_name",
    "registered_at",
    "status",
}


@pytest.mark.asyncio
async def test_v012_creates_projection_agents_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"] for c in inspect(sc).get_columns("projection_agents")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v012_person_id_unique() -> None:
    """UNIQUE constraint on person_id rejects duplicates (one Person per agent)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_agents "
                "(id, company_id, person_id, external_provider, display_name, "
                " registered_at, status) "
                "VALUES ('a1', 'co1', 'p1', 'claude', 'X', "
                "'2026-05-11T00:00:00Z', 'active')"
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_agents "
                    "(id, company_id, person_id, external_provider, display_name, "
                    " registered_at, status) "
                    "VALUES ('a2', 'co1', 'p1', 'openai', 'Y', "
                    "'2026-05-11T00:00:00Z', 'active')"
                )
            )


def test_v012_registered_in_canonical_migrations() -> None:
    """V012 lives in MIGRATIONS, monotonic and gap-free."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 12 in versions, f"expected v12 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
