"""v015 migration — projection_credentials.

Semantic Layer Wave 2 Task 1: lifecycle of every CredentialBroker-issued,
scoped, time-bounded token. Single kind with status field per Addendum
3; covers both data tokens (Snowflake / dbt) and model tokens (Anthropic
/ Kimi).
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v015_projection_credentials import (
    Migration,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "agent_id",
    "credential_kind",
    "target",
    "status",
    "ttl_expires_at",
    "issued_by",
    "issued_at",
}


@pytest.mark.asyncio
async def test_v015_creates_projection_credentials_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_credentials")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v015_status_check_constraint() -> None:
    """CHECK on status enforces {active, revoked}; rejects unknown."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    # Both valid statuses insert cleanly.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_credentials "
                "(id, company_id, agent_id, credential_kind, target, status, "
                " ttl_expires_at, issued_by, issued_at) "
                "VALUES ('c1', 'co1', 'a1', 'data', 'snowflake://x', 'active', "
                "'2026-05-11T18:00:00Z', 'agent-gateway', "
                "'2026-05-11T00:00:00Z')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO projection_credentials "
                "(id, company_id, agent_id, credential_kind, target, status, "
                " ttl_expires_at, issued_by, issued_at) "
                "VALUES ('c2', 'co1', 'a1', 'model', 'kimi', 'revoked', "
                "'2026-05-11T18:00:00Z', 'agent-gateway', "
                "'2026-05-11T00:00:00Z')"
            )
        )
    # Unknown status rejected.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_credentials "
                    "(id, company_id, agent_id, credential_kind, target, status, "
                    " ttl_expires_at, issued_by, issued_at) "
                    "VALUES ('c3', 'co1', 'a1', 'data', 'x', 'expired', "
                    "'2026-05-11T18:00:00Z', 'agent-gateway', "
                    "'2026-05-11T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v015_credential_kind_check_constraint() -> None:
    """CHECK on credential_kind rejects values outside {data, model}."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_credentials "
                    "(id, company_id, agent_id, credential_kind, target, status, "
                    " ttl_expires_at, issued_by, issued_at) "
                    "VALUES ('c1', 'co1', 'a1', 'cabbage', 'x', 'active', "
                    "'2026-05-11T18:00:00Z', 'agent-gateway', "
                    "'2026-05-11T00:00:00Z')"
                )
            )


def test_v015_registered_in_canonical_migrations() -> None:
    """V015 lives in MIGRATIONS, monotonic and gap-free."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 15 in versions, f"expected v15 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
