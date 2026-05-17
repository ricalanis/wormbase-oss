"""Tests for ``ProjectionRunner`` (P1.1).

The runner is the architecturally-correct path that materialises the
in-memory ``Projections`` fold into the SQL ``projection_*`` tables on
a periodic timer. These tests verify:

- A single ``run_once`` after seeding the ledger populates the right
  rows.
- Tenant-reset detection (ledger wipe → smaller max_seq) rewinds the
  cursor and rebuilds.
- Idempotency: calling ``run_once`` twice yields the same row counts.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_core.projection_runner import ProjectionRunner
from wormbase_ledger import Ledger
from wormbase_ledger.db import session_scope
from wormbase_ledger.schema import (
    metadata as ledger_metadata,
    projection_persons,
    projection_roles,
    projection_sources,
)
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


@pytest_asyncio.fixture
async def db_ledger(tmp_path: Path) -> AsyncIterator[Ledger]:
    """SQLite-backed Ledger fixture with the schema pre-created."""
    db_file = tmp_path / f"runner_{uuid.uuid4().hex}.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(ledger_metadata.drop_all)
        await conn.run_sync(ledger_metadata.create_all)
    yield Ledger(engine)
    await engine.dispose()


async def _emit_source(ledger: Ledger, *, company_id: UUID, source_id: UUID) -> None:
    async with session_scope(ledger.engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(source_id),
                "reason": "drop",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(source_id),
                    "source_kind": "file",
                    "uri": "file:///tmp/local-lake/q3.csv",
                    "added_via_flow": "drop_and_profile",
                    "suggested_domain": "finance",
                    "suggested_classification": "internal",
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_person(
    ledger: Ledger,
    *,
    company_id: UUID,
    person_id: UUID,
    name: str = "Bob",
) -> None:
    async with session_scope(ledger.engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "person_proposed",
                "ref_id": str(person_id),
                "reason": "auto-discovery",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_person_proposed",
                "args": {
                    "person_id": str(person_id),
                    "tenant_id": str(company_id),
                    "name": name,
                    "email": f"{name.lower()}@example.co",
                    "platform": "slack",
                    "platform_user_id": f"U-{name}",
                    "proposed_by": "worm",
                    "position": None,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_role(
    ledger: Ledger,
    *,
    company_id: UUID,
    person_id: UUID,
    role: str,
    granted_by: UUID,
) -> None:
    async with session_scope(ledger.engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "role_assigned",
                "ref_id": str(person_id),
                "reason": "default",
                "proposed_by": str(granted_by),
            },
            execute_fn=lambda: {
                "tool": "emit_role_assigned",
                "args": {
                    "person_id": str(person_id),
                    "role": role,
                    "granted_by": str(granted_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# run_once — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_populates_projection_tables(db_ledger: Ledger) -> None:
    company_id = uuid4()
    source_id = uuid4()
    bob = uuid4()
    granter = uuid4()

    await _emit_source(db_ledger, company_id=company_id, source_id=source_id)
    await _emit_person(db_ledger, company_id=company_id, person_id=bob, name="Bob")
    await _emit_role(
        db_ledger, company_id=company_id, person_id=bob, role="member",
        granted_by=granter,
    )

    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
    folded = await runner.run_once()
    assert folded > 0  # something happened

    async with db_ledger.engine.begin() as conn:
        sources = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()
        persons = (
            await conn.execute(
                select(projection_persons).where(
                    projection_persons.c.tenant_id == company_id
                )
            )
        ).mappings().all()
        roles = (
            await conn.execute(
                select(projection_roles).where(
                    projection_roles.c.tenant_id == company_id
                )
            )
        ).mappings().all()
    assert len(sources) == 1
    assert sources[0]["source_id"] == source_id
    assert len(persons) == 1
    assert persons[0]["name"] == "Bob"
    assert len(roles) == 1
    assert roles[0]["role"] == "member"


@pytest.mark.asyncio
async def test_run_once_idempotent(db_ledger: Ledger) -> None:
    company_id = uuid4()
    source_id = uuid4()
    await _emit_source(db_ledger, company_id=company_id, source_id=source_id)

    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
    await runner.run_once()
    second = await runner.run_once()
    # Second pass: no new ledger rows, so 0 work.
    assert second == 0

    async with db_ledger.engine.begin() as conn:
        sources = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_run_once_picks_up_new_rows_after_first_pass(
    db_ledger: Ledger,
) -> None:
    company_id = uuid4()
    a = uuid4()
    b = uuid4()
    await _emit_source(db_ledger, company_id=company_id, source_id=a)

    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
    await runner.run_once()

    # Second source arrives later.
    await _emit_source(db_ledger, company_id=company_id, source_id=b)
    second = await runner.run_once()
    assert second > 0

    async with db_ledger.engine.begin() as conn:
        sources = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()
    assert {r["source_id"] for r in sources} == {a, b}


# ---------------------------------------------------------------------------
# Tenant-reset detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_reset_rewinds_and_rebuilds(db_ledger: Ledger) -> None:
    company_id = uuid4()
    a = uuid4()
    await _emit_source(db_ledger, company_id=company_id, source_id=a)

    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
    await runner.run_once()
    assert runner.last_seq > 0
    pre_reset_seq = runner.last_seq

    # Wipe the tenant's ledger rows directly (mimics a tenant reset).
    from sqlalchemy import delete as _delete
    from wormbase_ledger.schema import ledger as ledger_table
    async with db_ledger.engine.begin() as conn:
        await conn.execute(
            _delete(ledger_table).where(ledger_table.c.company_id == company_id)
        )

    # Re-seed with a different source. max_seq starts back at 4 (one PEVR
    # cycle = 4 entries) which is < pre_reset_seq, so the runner should
    # detect the reset and rebuild from scratch.
    b = uuid4()
    await _emit_source(db_ledger, company_id=company_id, source_id=b)
    folded = await runner.run_once()
    assert folded > 0
    assert runner.last_seq < pre_reset_seq or runner.last_seq == 4

    async with db_ledger.engine.begin() as conn:
        sources = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()
    # Only `b` should remain — `a` was wiped.
    assert {r["source_id"] for r in sources} == {b}


@pytest.mark.asyncio
async def test_tenant_with_empty_ledger_rewinds_to_zero(db_ledger: Ledger) -> None:
    """If the runner had a non-zero cursor and the ledger is now empty,
    it rewinds to 0 and clears the projections."""
    company_id = uuid4()
    a = uuid4()
    await _emit_source(db_ledger, company_id=company_id, source_id=a)
    runner = ProjectionRunner(db_ledger, company_id, poll_interval_s=0.1)
    await runner.run_once()
    assert runner.last_seq > 0

    from sqlalchemy import delete as _delete
    from wormbase_ledger.schema import ledger as ledger_table
    async with db_ledger.engine.begin() as conn:
        await conn.execute(
            _delete(ledger_table).where(ledger_table.c.company_id == company_id)
        )

    folded = await runner.run_once()
    assert folded == 0
    assert runner.last_seq == 0

    async with db_ledger.engine.begin() as conn:
        sources = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()
    assert sources == []
