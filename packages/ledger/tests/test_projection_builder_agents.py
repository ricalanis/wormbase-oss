"""Projection-fold tests for ``agent_registered`` + ``agent_grant`` (Wave 3 Task 2).

The /people/agents dashboard surface reads two projection rows:

* ``projection_agents``       — one row per registered agent (Person sub-type)
* ``projection_agent_grants`` — one row per (agent_id, grant_kind, grant_target)

The projection builder folds ``emit_agent_registered`` execute payloads into the
agents projection and ``emit_agent_grant`` execute payloads into the agent_grants
projection. Per doctrine Addendum 3, ``agent_grant`` is a SINGLE kind with a
``status`` field — assign and revoke land on the same row keyed by the triple,
with the latest write's ``status`` + ``granted_at`` winning.

These tests pin:

* one ``agent_registered`` PEVR → one row in ``projections.agents`` (status="active")
* one ``agent_grant`` (status="active") PEVR → one row in ``projections.agent_grants``
* a second ``agent_grant`` with status="revoked" for the SAME triple → UPSERT:
  same row id, status flips to "revoked", granted_at updates to the new write
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r):  # type: ignore[no-untyped-def]
    return {"checks": [], "passed": True}


def _resolve_keep(_v):  # type: ignore[no-untyped-def]
    return {"outcome": "keep", "rationale": "ok"}


@pytest.mark.asyncio
async def test_agent_registered_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``agent_registered`` PEVR → one row in ``projections.agents``."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_id = str(uuid4())
    person_id = agent_id  # 1:1 with person_id in v1
    admin_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "agent_registered",
                "ref_id": agent_id,
                "reason": "admin registered claude_research",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_registered",
                "args": {
                    "agent_id": agent_id,
                    "person_id": person_id,
                    "company_id": str(company_id),
                    "external_provider": "claude",
                    "display_name": "Claude Research Agent",
                    "registered_by": admin_id,
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.agents) == 1
    row = proj.agents[0]
    assert row["id"] == agent_id
    assert row["person_id"] == person_id
    assert row["company_id"] == str(company_id)
    assert row["external_provider"] == "claude"
    assert row["display_name"] == "Claude Research Agent"
    assert row["status"] == "active"
    assert isinstance(row["registered_at"], datetime)


@pytest.mark.asyncio
async def test_agent_grant_active_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``agent_grant`` (status='active') PEVR → one projection row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "agent_grant",
                "ref_id": agent_id,
                "reason": "admin granted domain.read on finance",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_grant",
                "args": {
                    "agent_id": agent_id,
                    "company_id": str(company_id),
                    "grant_kind": "domain.read",
                    "grant_target": domain_id,
                    "status": "active",
                    "granted_by": admin_id,
                    "budget_remaining_usd": None,
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.agent_grants) == 1
    row = proj.agent_grants[0]
    assert row["agent_id"] == agent_id
    assert row["grant_kind"] == "domain.read"
    assert row["grant_target"] == domain_id
    assert row["status"] == "active"
    assert row["granted_by"] == admin_id
    assert row["budget_remaining_usd"] is None


@pytest.mark.asyncio
async def test_agent_grant_revoke_upserts_same_row(
    test_database_url: str,
) -> None:
    """A second agent_grant write with status='revoked' for the SAME triple
    upserts onto the same row id, with status now 'revoked' and granted_at
    updated to the new write timestamp. Addendum 3 status-field
    consolidation: one row per triple, regardless of how many times the
    grant gets toggled.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_id = str(uuid4())
    admin_id = str(uuid4())
    domain_id = str(uuid4())

    first_ts = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
    second_ts = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "agent_grant",
                "ref_id": agent_id,
                "reason": "initial grant",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_grant",
                "args": {
                    "agent_id": agent_id,
                    "company_id": str(company_id),
                    "grant_kind": "domain.read",
                    "grant_target": domain_id,
                    "status": "active",
                    "granted_by": admin_id,
                    "budget_remaining_usd": None,
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
            timestamp=first_ts,
        )

    async with session_scope(engine) as session:
        proj_after_grant = await build_projections(session, company_id)
    assert len(proj_after_grant.agent_grants) == 1
    grant_row = proj_after_grant.agent_grants[0]
    initial_id = grant_row["id"]
    assert grant_row["status"] == "active"
    assert grant_row["granted_at"] == first_ts

    # Second write: revoke the SAME (agent_id, grant_kind, grant_target).
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "agent_grant",
                "ref_id": agent_id,
                "reason": "admin revoked grant",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_grant",
                "args": {
                    "agent_id": agent_id,
                    "company_id": str(company_id),
                    "grant_kind": "domain.read",
                    "grant_target": domain_id,
                    "status": "revoked",
                    "granted_by": admin_id,
                    "budget_remaining_usd": None,
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
            timestamp=second_ts,
        )

    async with session_scope(engine) as session:
        proj_after_revoke = await build_projections(session, company_id)

    # Still exactly one row — UPSERT preserves the row id, flips status.
    assert len(proj_after_revoke.agent_grants) == 1
    revoked = proj_after_revoke.agent_grants[0]
    assert revoked["id"] == initial_id
    assert revoked["status"] == "revoked"
    assert revoked["granted_at"] == second_ts
    assert revoked["agent_id"] == agent_id
    assert revoked["grant_kind"] == "domain.read"
    assert revoked["grant_target"] == domain_id


@pytest.mark.asyncio
async def test_agent_grant_model_access_carries_budget(
    test_database_url: str,
) -> None:
    """model.access grants carry budget_remaining_usd; the projection
    preserves it across the fold."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_id = str(uuid4())
    admin_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "agent_grant",
                "ref_id": agent_id,
                "reason": "model access granted with $5.00 budget",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_grant",
                "args": {
                    "agent_id": agent_id,
                    "company_id": str(company_id),
                    "grant_kind": "model.access",
                    "grant_target": "kimi",
                    "status": "active",
                    "granted_by": admin_id,
                    "budget_remaining_usd": "5.00",
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.agent_grants) == 1
    row = proj.agent_grants[0]
    assert row["grant_kind"] == "model.access"
    assert row["grant_target"] == "kimi"
    assert row["budget_remaining_usd"] == "5.00"


@pytest.mark.asyncio
async def test_agents_projection_is_tenant_scoped(
    test_database_url: str,
) -> None:
    """An agent registered in tenant A is invisible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    agent_id = str(uuid4())
    admin_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=tenant_a,
            propose={
                "target_kind": "agent_registered",
                "ref_id": agent_id,
                "reason": "tenant A agent",
                "proposed_by": admin_id,
            },
            execute_fn=lambda: {
                "tool": "emit_agent_registered",
                "args": {
                    "agent_id": agent_id,
                    "person_id": agent_id,
                    "company_id": str(tenant_a),
                    "external_provider": "openai",
                    "display_name": "tenant-A agent",
                    "registered_by": admin_id,
                },
                "result_ref": agent_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.agents) == 1
    assert len(proj_b.agents) == 0
