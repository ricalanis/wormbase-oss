"""v014 migration — projection_agent_queries.

Semantic Layer Wave 2 Task 1: PEVR-collapsed view of every
``agent_query`` lifecycle. Single kind, phase field per Addendum 3;
the projection rolls all four PEVR entries up to one row keyed on
``audit_trail_id``.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v014_projection_agent_queries import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "agent_id",
    "mcp_tool",
    "args",
    "route_mode",
    "status",
    "row_count",
    "cost_usd",
    "latency_ms",
    "caused_by",
    "started_at",
}


@pytest.mark.asyncio
async def test_v014_creates_projection_agent_queries_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_agent_queries")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v014_status_check_includes_denied() -> None:
    """CHECK on status accepts {propose, execute, verify, resolve, denied}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        # Each valid status inserts cleanly.
        for i, status in enumerate(
            ("propose", "execute", "verify", "resolve", "denied")
        ):
            await conn.execute(
                text(
                    "INSERT INTO projection_agent_queries "
                    "(id, company_id, agent_id, mcp_tool, args, route_mode, "
                    " status, started_at) "
                    f"VALUES ('q{i}', 'co1', 'a1', 't', '{{}}', 'broker', "
                    f"'{status}', '2026-05-11T00:00:00Z')"
                )
            )
    # Unknown status rejected.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_agent_queries "
                    "(id, company_id, agent_id, mcp_tool, args, route_mode, "
                    " status, started_at) "
                    "VALUES ('qx', 'co1', 'a1', 't', '{}', 'broker', "
                    "'unknown', '2026-05-11T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v014_route_mode_check_constraint() -> None:
    """CHECK on route_mode rejects values outside {broker, federate}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_agent_queries "
                    "(id, company_id, agent_id, mcp_tool, args, route_mode, "
                    " status, started_at) "
                    "VALUES ('q1', 'co1', 'a1', 't', '{}', 'rogue', "
                    "'propose', '2026-05-11T00:00:00Z')"
                )
            )


def test_v014_registered_in_canonical_migrations() -> None:
    """V014 lives in MIGRATIONS, monotonic and gap-free."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 14 in versions, f"expected v14 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
