"""Tests for ``persist_projections`` (P1.1).

The in-memory ``Projections`` fold is the canonical source of truth; this
suite verifies that ``persist_projections`` materialises the dataclass into
the SQL ``projection_*`` tables byte-for-byte and is idempotent under
re-application.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import (
    build_projections,
    persist_projections,
)
from wormbase_ledger.schema import (
    projection_installs,
    projection_persons,
    projection_roles,
    projection_sources,
)
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_source(
    engine: Any, *, company_id: UUID, source_id: UUID,
) -> None:
    async with session_scope(engine) as session:
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
                    "uri": "file:///tmp/x.csv",
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
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    name: str = "Bob",
) -> None:
    async with session_scope(engine) as session:
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
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    role: str = "member",
    granted_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "role_assigned",
                "ref_id": str(person_id),
                "reason": "default member",
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


async def _emit_install(
    engine: Any,
    *,
    company_id: UUID,
    install_id: UUID,
    installer_person_id: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "install_completed",
                "ref_id": str(install_id),
                "reason": "OAuth completed",
                "proposed_by": str(installer_person_id),
            },
            execute_fn=lambda: {
                "tool": "emit_install_completed",
                "args": {
                    "install_id": str(install_id),
                    "tenant_id": str(company_id),
                    "platform": "slack",
                    "installer_person_id": str(installer_person_id),
                    "oauth_grant_ref": "oauth-ref-123",
                    "scopes": ["chat:write", "channels:history"],
                    "bot_user_id": "U-bot",
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# Persist tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_projections_writes_sources_row(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    await _emit_source(engine, company_id=company_id, source_id=source_id)

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_sources).where(
                    projection_sources.c.company_id == company_id
                )
            )
        ).mappings().all()

    assert len(rows) == 1
    assert rows[0]["source_id"] == source_id
    assert rows[0]["status"] == "proposed"
    assert rows[0]["company_id"] == company_id


@pytest.mark.asyncio
async def test_persist_projections_writes_persons_and_roles(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    bob = uuid4()
    carol = uuid4()
    granter = uuid4()

    await _emit_person(engine, company_id=company_id, person_id=bob, name="Bob")
    await _emit_person(engine, company_id=company_id, person_id=carol, name="Carol")
    await _emit_role(
        engine, company_id=company_id, person_id=bob, granted_by=granter,
    )
    await _emit_role(
        engine, company_id=company_id, person_id=carol,
        role="admin", granted_by=granter,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
        person_rows = (
            await conn.execute(
                select(projection_persons).where(
                    projection_persons.c.tenant_id == company_id
                )
            )
        ).mappings().all()
        role_rows = (
            await conn.execute(
                select(projection_roles).where(
                    projection_roles.c.tenant_id == company_id
                )
            )
        ).mappings().all()

    assert {r["name"] for r in person_rows} == {"Bob", "Carol"}
    assert len(role_rows) == 2
    assert {r["role"] for r in role_rows} == {"member", "admin"}


@pytest.mark.asyncio
async def test_persist_projections_writes_install_with_setup_mode_null(
    test_database_url: str,
) -> None:
    """Block I G1 column should land via the persist path with NULL by default."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    installer = uuid4()
    install_id = uuid4()

    await _emit_install(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)
    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_installs).where(
                    projection_installs.c.tenant_id == company_id
                )
            )
        ).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    # Setup-mode column landed; default is NULL pre-T2-fork.
    assert "setup_mode" in row
    assert row["setup_mode"] is None
    assert "setup_completed_at" in row
    assert row["setup_completed_at"] is None


@pytest.mark.asyncio
async def test_persist_projections_idempotent(test_database_url: str) -> None:
    """Calling persist_projections twice produces the same row set."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    bob = uuid4()
    granter = uuid4()
    await _emit_source(engine, company_id=company_id, source_id=source_id)
    await _emit_person(engine, company_id=company_id, person_id=bob, name="Bob")
    await _emit_role(
        engine, company_id=company_id, person_id=bob, granted_by=granter,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)
    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
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
    assert len(persons) == 1
    assert len(roles) == 1


@pytest.mark.asyncio
async def test_persist_projections_tenant_scoped_does_not_clobber_other(
    test_database_url: str,
) -> None:
    """A persist for tenant A must not delete tenant B's rows."""
    engine = get_engine(test_database_url)
    a = uuid4()
    b = uuid4()
    a_source = uuid4()
    b_source = uuid4()
    await _emit_source(engine, company_id=a, source_id=a_source)
    await _emit_source(engine, company_id=b, source_id=b_source)

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, a)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, b)

    async with engine.begin() as conn:
        await persist_projections(conn, a, proj_a)
        await persist_projections(conn, b, proj_b)

    # Re-persist A and confirm B's row still present.
    async with engine.begin() as conn:
        await persist_projections(conn, a, proj_a)

    async with engine.begin() as conn:
        rows = (
            await conn.execute(select(projection_sources))
        ).mappings().all()
    company_to_source = {r["company_id"]: r["source_id"] for r in rows}
    assert company_to_source.get(a) == a_source
    assert company_to_source.get(b) == b_source
