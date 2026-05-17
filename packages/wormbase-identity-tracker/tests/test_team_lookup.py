"""Team lookup tests — moved from apps/worm-core/tests/test_team_lookup.py.

Identical to the original; only the import path changed:
  - `from wormbase_core import team_lookup`
  + `from wormbase_identity_tracker import team_lookup`

W5.A4 — Team-Domain membership lookup tests.

Drives :mod:`wormbase_identity_tracker.team_lookup` against an InMemoryLedger
seeded with ``emit_domain_role_assigned`` execute rows. A "Team" is a Domain
that one or more Persons hold a domain-facet grant on.

Invariants tested:

* ``team_for_person`` returns every Team-Domain UUID the Person belongs to.
* ``members_of_team`` returns every Person UUID that holds a grant on the
  Team-Domain. Both ``owner`` and ``contributor`` grants count.
* ``all_teams`` returns the union of every Team-Domain referenced by the
  ledger (drives the cli boot-time team-loop registration).
* Empty ledger returns empty sets.
* Two teams with overlapping membership project correctly (a Person who
  belongs to both teams shows up in ``team_for_person`` for both, and in
  ``members_of_team`` for both).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from wormbase_identity_tracker import team_lookup


# Stable UUIDs so the assertions read cleanly.
GROWTH_TEAM = UUID("00000000-0000-0000-0000-0000000000a1")
RETENTION_TEAM = UUID("00000000-0000-0000-0000-0000000000a2")
PLATFORM_TEAM = UUID("00000000-0000-0000-0000-0000000000a3")

CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
DAVE = UUID("00000000-0000-0000-0000-0000000000c2")
EVE = UUID("00000000-0000-0000-0000-0000000000c3")
FRED = UUID("00000000-0000-0000-0000-0000000000c4")
GINA = UUID("00000000-0000-0000-0000-0000000000c5")
HANK = UUID("00000000-0000-0000-0000-0000000000c6")
INSTALLER = UUID("00000000-0000-0000-0000-0000000000d0")

NOW = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)


async def _grant_domain_role(
    ledger,
    company_id: UUID,
    person_id: UUID,
    domain_id: UUID,
    role: str = "contributor",
) -> None:
    """Seed an emit_domain_role_assigned PEVR cycle for the test ledger."""
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "domain_role_assigned",
            "ref_id": str(person_id),
            "reason": f"team test: grant {role} on {domain_id}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_domain_role_assigned",
            "args": {
                "person_id": str(person_id),
                "domain_id": str(domain_id),
                "role": role,
                "granted_by": str(INSTALLER),
            },
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _seed_two_teams(ledger, company_id: UUID) -> None:
    """Growth: Carol+Dave+Eve. Retention: Eve+Fred+Gina+Hank.

    Eve is in both teams to exercise the overlap projection.
    """
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, DAVE, GROWTH_TEAM)
    await _grant_domain_role(ledger, company_id, EVE, GROWTH_TEAM)
    await _grant_domain_role(ledger, company_id, EVE, RETENTION_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, FRED, RETENTION_TEAM)
    await _grant_domain_role(ledger, company_id, GINA, RETENTION_TEAM)
    await _grant_domain_role(ledger, company_id, HANK, RETENTION_TEAM)


# ----------------------------------------------------------------------
# Empty-state behaviour
# ----------------------------------------------------------------------


async def test_team_for_person_empty_ledger(ledger, company_id):
    teams = await team_lookup.team_for_person(ledger, company_id, CAROL)
    assert teams == set()


async def test_members_of_team_empty_ledger(ledger, company_id):
    members = await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM)
    assert members == set()


async def test_all_teams_empty_ledger(ledger, company_id):
    teams = await team_lookup.all_teams(ledger, company_id)
    assert teams == set()


# ----------------------------------------------------------------------
# Single-team membership
# ----------------------------------------------------------------------


async def test_team_for_person_single_team(ledger, company_id):
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "owner")
    teams = await team_lookup.team_for_person(ledger, company_id, CAROL)
    assert teams == {GROWTH_TEAM}


async def test_members_of_team_single_team(ledger, company_id):
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, DAVE, GROWTH_TEAM)
    members = await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM)
    assert members == {CAROL, DAVE}


# ----------------------------------------------------------------------
# Two-team fixture: Growth + Retention with overlap
# ----------------------------------------------------------------------


async def test_team_for_person_growth_only(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    assert await team_lookup.team_for_person(ledger, company_id, CAROL) == {GROWTH_TEAM}
    assert await team_lookup.team_for_person(ledger, company_id, DAVE) == {GROWTH_TEAM}


async def test_team_for_person_retention_only(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    assert await team_lookup.team_for_person(ledger, company_id, FRED) == {RETENTION_TEAM}
    assert await team_lookup.team_for_person(ledger, company_id, GINA) == {RETENTION_TEAM}
    assert await team_lookup.team_for_person(ledger, company_id, HANK) == {RETENTION_TEAM}


async def test_team_for_person_overlap_returns_both(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    teams = await team_lookup.team_for_person(ledger, company_id, EVE)
    assert teams == {GROWTH_TEAM, RETENTION_TEAM}


async def test_members_of_growth_team(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    members = await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM)
    assert members == {CAROL, DAVE, EVE}


async def test_members_of_retention_team(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    members = await team_lookup.members_of_team(ledger, company_id, RETENTION_TEAM)
    assert members == {EVE, FRED, GINA, HANK}


async def test_all_teams_returns_union(ledger, company_id):
    await _seed_two_teams(ledger, company_id)
    teams = await team_lookup.all_teams(ledger, company_id)
    assert teams == {GROWTH_TEAM, RETENTION_TEAM}


async def test_owner_and_contributor_grants_both_count(ledger, company_id):
    """Domain-facet grants come in two roles; both confer Team membership."""
    await _grant_domain_role(ledger, company_id, CAROL, PLATFORM_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, DAVE, PLATFORM_TEAM, "contributor")
    members = await team_lookup.members_of_team(ledger, company_id, PLATFORM_TEAM)
    assert members == {CAROL, DAVE}


async def test_team_lookup_isolated_per_tenant(ledger, company_id):
    """A grant on a different ``company_id`` doesn't leak into the result."""
    other_company = UUID("00000000-0000-0000-0000-0000000000bb")
    await _grant_domain_role(ledger, other_company, CAROL, GROWTH_TEAM, "owner")
    # Same Carol, same team, but on a different tenant — must not appear.
    teams = await team_lookup.team_for_person(ledger, company_id, CAROL)
    assert teams == set()
    members = await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM)
    assert members == set()
    # Reading the other tenant should return the seeded grant.
    teams_other = await team_lookup.team_for_person(ledger, other_company, CAROL)
    assert teams_other == {GROWTH_TEAM}


async def test_team_lookup_ignores_non_domain_role_entries(ledger, company_id):
    """Tenancy + resource-facet grants must not be mistaken for Team membership."""
    # Seed a tenancy-facet grant — must NOT appear as a Team-Domain.
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "role_assigned",
            "ref_id": str(CAROL),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_role_assigned",
            "args": {
                "person_id": str(CAROL),
                "role": "admin",
                "granted_by": str(INSTALLER),
            },
            "result_ref": str(CAROL),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    # Seed a resource-facet grant (kpi).
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "resource_role_assigned",
            "ref_id": str(CAROL),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_resource_role_assigned",
            "args": {
                "person_id": str(CAROL),
                "resource_id": str(GROWTH_TEAM),
                "resource_type": "kpi",
                "role": "maintainer",
                "granted_by": str(INSTALLER),
            },
            "result_ref": str(CAROL),
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    # Neither helper should treat these as Team membership.
    assert await team_lookup.team_for_person(ledger, company_id, CAROL) == set()
    assert await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM) == set()
    assert await team_lookup.all_teams(ledger, company_id) == set()


async def test_repeat_grants_idempotent_in_set(ledger, company_id):
    """Two consecutive grants of the same role collapse to one set member."""
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "owner")
    await _grant_domain_role(ledger, company_id, CAROL, GROWTH_TEAM, "contributor")
    teams = await team_lookup.team_for_person(ledger, company_id, CAROL)
    assert teams == {GROWTH_TEAM}
    members = await team_lookup.members_of_team(ledger, company_id, GROWTH_TEAM)
    assert members == {CAROL}
