"""Role projection replay tests (Block A2 of the production-dashboard PRD).

Each test drives the canonical write_primitive (`propose → execute → verify
→ resolve`) so the resulting `execute` envelope carries
`payload["tool"] == "emit_<kind>"`, then folds the ledger via
`build_projections` and asserts on `projections.roles`.

Coverage:
    * tenancy assign-only (revoked_at None)
    * tenancy assign-then-revoke (revoked_at populated)
    * domain assign populates facet/scope_id/scope_type
    * resource assign populates facet/scope_id/scope_type
    * replay determinism: stable grant_ids across two replays
    * composability: one Person can hold N grants across all three facets;
      ``grants_for(projections, person_id)`` returns the full role surface.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections, grants_for
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


# ---------------------------------------------------------------------------
# Per-kind emit helpers (one async helper per ledger kind).
# ---------------------------------------------------------------------------


async def _emit_role_assigned(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    role: str,
    granted_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "role_assigned",
                "ref_id": str(person_id),
                "reason": "grant",
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


async def _emit_role_revoked(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    role: str,
    revoked_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "role_revoked",
                "ref_id": str(person_id),
                "reason": "revoke",
                "proposed_by": str(revoked_by),
            },
            execute_fn=lambda: {
                "tool": "emit_role_revoked",
                "args": {
                    "person_id": str(person_id),
                    "role": role,
                    "revoked_by": str(revoked_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_domain_role_assigned(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    domain_id: UUID,
    role: str,
    granted_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "domain_role_assigned",
                "ref_id": str(domain_id),
                "reason": "grant",
                "proposed_by": str(granted_by),
            },
            execute_fn=lambda: {
                "tool": "emit_domain_role_assigned",
                "args": {
                    "person_id": str(person_id),
                    "domain_id": str(domain_id),
                    "role": role,
                    "granted_by": str(granted_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_resource_role_assigned(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    resource_id: UUID,
    resource_type: str,
    role: str,
    granted_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "resource_role_assigned",
                "ref_id": str(resource_id),
                "reason": "grant",
                "proposed_by": str(granted_by),
            },
            execute_fn=lambda: {
                "tool": "emit_resource_role_assigned",
                "args": {
                    "person_id": str(person_id),
                    "resource_id": str(resource_id),
                    "resource_type": resource_type,
                    "role": role,
                    "granted_by": str(granted_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# Tenancy facet: assign + revoke.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_assigned_creates_unrevoked_grant(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.roles) == 1
    g = proj.roles[0]
    assert g["facet"] == "tenancy"
    assert g["role"] == "admin"
    assert g["person_id"] == person_id
    assert g["tenant_id"] == company_id
    assert g["granted_by"] == admin
    assert g["scope_id"] is None
    assert g["scope_type"] is None
    assert g["revoked_at"] is None
    assert g["granted_at"] is not None


@pytest.mark.asyncio
async def test_role_revoked_stamps_matching_grant(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )
    await _emit_role_revoked(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        revoked_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.roles) == 1
    g = proj.roles[0]
    assert g["role"] == "admin"
    assert g["revoked_at"] is not None
    assert g["granted_at"] is not None
    # revoke is later than (or equal to) grant in wallclock terms.
    assert g["revoked_at"] >= g["granted_at"]


@pytest.mark.asyncio
async def test_role_revoked_only_targets_matching_role(
    test_database_url: str,
) -> None:
    """Revoking 'admin' must NOT touch a separate 'member' grant."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )
    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="member",
        granted_by=admin,
    )
    await _emit_role_revoked(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        revoked_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    by_role = {g["role"]: g for g in proj.roles}
    assert by_role["admin"]["revoked_at"] is not None
    assert by_role["member"]["revoked_at"] is None


# ---------------------------------------------------------------------------
# Domain facet.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_domain_role_assigned_populates_scope(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    domain_id = uuid4()
    admin = uuid4()

    await _emit_domain_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        domain_id=domain_id,
        role="owner",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.roles) == 1
    g = proj.roles[0]
    assert g["facet"] == "domain"
    assert g["role"] == "owner"
    assert g["scope_id"] == domain_id
    assert g["scope_type"] == "domain"
    assert g["revoked_at"] is None


# ---------------------------------------------------------------------------
# Resource facet.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_role_assigned_populates_scope(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    resource_id = uuid4()
    admin = uuid4()

    await _emit_resource_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        resource_id=resource_id,
        resource_type="kpi",
        role="maintainer",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.roles) == 1
    g = proj.roles[0]
    assert g["facet"] == "resource"
    assert g["role"] == "maintainer"
    assert g["scope_id"] == resource_id
    assert g["scope_type"] == "kpi"
    assert g["revoked_at"] is None


# ---------------------------------------------------------------------------
# Determinism: same ledger replayed twice → identical grant_ids.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_replay_is_deterministic(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    domain_id = uuid4()
    resource_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )
    await _emit_domain_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        domain_id=domain_id,
        role="owner",
        granted_by=admin,
    )
    await _emit_resource_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        resource_id=resource_id,
        resource_type="source",
        role="maintainer",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert proj_a.roles == proj_b.roles
    # grant_ids derived from sha256(tenant|person|facet|role|scope|seq) so
    # they MUST be identical across replays.
    ids_a = [g["grant_id"] for g in proj_a.roles]
    ids_b = [g["grant_id"] for g in proj_b.roles]
    assert ids_a == ids_b


# ---------------------------------------------------------------------------
# Composability: a Person can hold N grants across all three facets.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_holds_grants_across_all_facets(
    test_database_url: str,
) -> None:
    """A single Person carries 4 grants — 1 tenancy + 1 domain + 2 resource —
    and ``grants_for`` returns the full role surface.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    domain_id = uuid4()
    resource_id_kpi = uuid4()
    resource_id_source = uuid4()
    admin = uuid4()

    # 1: tenancy.admin
    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )
    # 2: domain.owner(finance)
    await _emit_domain_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        domain_id=domain_id,
        role="owner",
        granted_by=admin,
    )
    # 3: resource.maintainer(kpi.q3_net_revenue)
    await _emit_resource_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        resource_id=resource_id_kpi,
        resource_type="kpi",
        role="maintainer",
        granted_by=admin,
    )
    # 4: resource.maintainer(source.stripe)
    await _emit_resource_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        resource_id=resource_id_source,
        resource_type="source",
        role="maintainer",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    grants = grants_for(proj, person_id)
    assert len(grants) == 4

    facets = sorted(g["facet"] for g in grants)
    assert facets == ["domain", "resource", "resource", "tenancy"]

    # Resource grants discriminate by resource_type.
    resource_grants = [g for g in grants if g["facet"] == "resource"]
    types = sorted(g["scope_type"] for g in resource_grants)
    assert types == ["kpi", "source"]

    # Tenancy grant has no scope.
    tenancy = next(g for g in grants if g["facet"] == "tenancy")
    assert tenancy["role"] == "admin"
    assert tenancy["scope_id"] is None
    assert tenancy["scope_type"] is None

    # Domain grant.
    dom = next(g for g in grants if g["facet"] == "domain")
    assert dom["role"] == "owner"
    assert dom["scope_id"] == domain_id
    assert dom["scope_type"] == "domain"


@pytest.mark.asyncio
async def test_grants_for_excludes_revoked(test_database_url: str) -> None:
    """A revoked tenancy grant must not appear in ``grants_for`` output."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        granted_by=admin,
    )
    await _emit_role_revoked(
        engine,
        company_id=company_id,
        person_id=person_id,
        role="admin",
        revoked_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Projection still has the row (with revoked_at set) for audit replay.
    assert len(proj.roles) == 1
    # But grants_for filters it out.
    assert grants_for(proj, person_id) == []


@pytest.mark.asyncio
async def test_grants_for_isolates_persons(test_database_url: str) -> None:
    """``grants_for`` returns only the queried Person's grants."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    alice_id = uuid4()
    bob_id = uuid4()
    admin = uuid4()

    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=alice_id,
        role="admin",
        granted_by=admin,
    )
    await _emit_role_assigned(
        engine,
        company_id=company_id,
        person_id=bob_id,
        role="member",
        granted_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.roles) == 2
    alice_grants = grants_for(proj, alice_id)
    bob_grants = grants_for(proj, bob_id)
    assert len(alice_grants) == 1
    assert len(bob_grants) == 1
    assert alice_grants[0]["role"] == "admin"
    assert bob_grants[0]["role"] == "member"
