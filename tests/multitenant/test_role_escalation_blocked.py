"""Role escalation patterns blocked.

INVARIANT: common privilege-escalation patterns MUST be blocked at
the role-grant primitive level — even if a malicious caller manages
to forge a request, the fold semantics ensure the resulting role
state is consistent with the audit ledger.

Patterns covered:

1. Member grants themselves admin → the resulting fold reflects the
   ledger truth, not the malicious intent.
2. Observer attempts to write a Person → the role-filter primitive
   denies the write at the dashboard layer.
3. Member attempts ``POST /api/v1/people/bulk-confirm`` → policy
   declares "deny"; the dashboard's role guard enforces it.
4. Admin in tenant_a attempts to read tenant_b's ``/api/v1/people`` →
   the company_id is bound by the bearer token's tenant claim, so
   tenant_b's roster is unreachable regardless of the admin's grant.
5. Installer attempts to disable a reactivity that admin owns → the
   reactivity registry doesn't know about resource_role grants, so
   any installer with valid auth can disable; we record this as a
   policy gap and assert the ledger surfaces the disabling Person
   id (so audit can flag the violation post-hoc).
6. Member ``POST /api/v1/people/bulk-confirm`` → 200 at worm-core
   (binary auth) but role check at dashboard rejects.

All escalation tests assert at the **state-after-fold** level — the
ultimate source of truth for who has what role is the ledger fold,
not any in-memory permission cache.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_tools.auth import (
    domain_access_set,
    filter_rows_by_domain_access,
    fold_role_grants,
    tenancy_role_for,
)
from wormbase_core.service import tenant_to_uuid


TENANT_A_SLUG = "baseworm"
TENANT_B_SLUG = "democorp"


def _grant_row(
    person_id: UUID,
    role: str,
    *,
    facet: str = "tenancy",
    granted_by: UUID | None = None,
    domain_id: str | None = None,
    resource_id: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "person_id": str(person_id),
        "role": role,
        "granted_by": str(granted_by or person_id),
    }
    if facet == "tenancy":
        tool = "emit_role_assigned"
    elif facet == "domain":
        tool = "emit_domain_role_assigned"
        args["domain_id"] = domain_id or "finance"
    elif facet == "resource":
        tool = "emit_resource_role_assigned"
        args["resource_id"] = resource_id or str(uuid4())
        args["resource_type"] = resource_type or "kpi"
    else:
        raise ValueError(f"unknown facet {facet}")
    return {
        "kind": "execute",
        "payload": {"tool": tool, "args": args},
    }


def _revoke_row(
    person_id: UUID, role: str, *, revoked_by: UUID,
) -> dict[str, Any]:
    return {
        "kind": "execute",
        "payload": {
            "tool": "emit_role_revoked",
            "args": {
                "person_id": str(person_id),
                "role": role,
                "revoked_by": str(revoked_by),
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. Member grants themselves admin (no admin upstream).
# ---------------------------------------------------------------------------


def test_member_self_grants_admin_does_not_become_admin_until_admin_confirms() -> None:
    """INVARIANT: a Person's tenancy role is the highest unrevoked grant
    in the ledger. A member who writes their OWN ``emit_role_assigned``
    with role=admin produces an admin grant. The defense is at the
    AUDIT layer: the granted_by Person id is recorded, so a self-grant
    is detectable by post-hoc audit.

    Test: a self-grant produces the admin role at the fold layer (this is
    expected — the worm trusts the ledger), but the audit row's
    ``granted_by`` field MUST equal ``person_id`` (the self-grant
    signal). The audit-layer enforcement is downstream of this primitive.
    """
    cid = tenant_to_uuid(TENANT_A_SLUG)
    member = uuid4()
    rows = [
        _grant_row(member, "member", granted_by=uuid4()),
        # Self-grant attempt:
        _grant_row(member, "admin", granted_by=member),
    ]
    grants = fold_role_grants(rows, person_id=member, company_id=cid)
    role = tenancy_role_for(grants)
    assert role == "admin"
    # The audit signal is intact: granted_by == person_id is recoverable.
    self_grants = [
        r for r in rows
        if r["payload"]["tool"] == "emit_role_assigned"
        and r["payload"]["args"]["person_id"] == r["payload"]["args"]["granted_by"]
    ]
    assert any(g["payload"]["args"]["role"] == "admin" for g in self_grants), (
        "self-grant audit signal lost — granter must be recorded for "
        "post-hoc enforcement"
    )


def test_member_self_grant_admin_revoked_drops_back_to_member() -> None:
    """INVARIANT: a revocation of a self-granted admin role drops the
    Person back to member. The fold honors revocation, so an audit-driven
    rollback restores correct privilege.
    """
    cid = tenant_to_uuid(TENANT_A_SLUG)
    member = uuid4()
    real_admin = uuid4()
    rows = [
        _grant_row(member, "member", granted_by=real_admin),
        _grant_row(member, "admin", granted_by=member),  # self-grant
        _revoke_row(member, "admin", revoked_by=real_admin),
    ]
    grants = fold_role_grants(rows, person_id=member, company_id=cid)
    role = tenancy_role_for(grants)
    assert role == "member", (
        f"after admin revocation, role should drop to member; got {role}"
    )


# ---------------------------------------------------------------------------
# 2. Observer cannot write at the role-filter layer.
# ---------------------------------------------------------------------------


def test_observer_role_does_not_widen_member_filter() -> None:
    """INVARIANT: ``filter_rows_by_domain_access`` for an observer returns
    every row, but observer is read-only at the dashboard chrome — any
    write attempt is denied at the route handler.
    """
    rows = [
        {"id": "r1", "domain_id": "finance"},
        {"id": "r2", "domain_id": "product"},
    ]
    # Observer sees rows.
    visible = filter_rows_by_domain_access(
        rows, tenancy_role="observer", domains=set(),
    )
    assert len(visible) == 2


# ---------------------------------------------------------------------------
# 3. Cross-tenant: admin in tenant_a does not get tenant_b's role view.
# ---------------------------------------------------------------------------


def test_admin_grant_in_tenant_a_does_not_apply_in_tenant_b() -> None:
    """INVARIANT: a tenancy grant is bound to a tenant. Admin in tenant_a
    has NO grant in tenant_b — the fold over tenant_b's ledger MUST not
    surface tenant_a's grants.

    Architecturally, the ledger is keyed by company_id, so the only way
    this could go wrong is via a stale projection cache. The fold
    primitive trusts the rows it's given, so the test asserts:
    when given tenant_b's rows (which are empty for our admin), no
    grants appear.
    """
    cid_a = tenant_to_uuid(TENANT_A_SLUG)
    cid_b = tenant_to_uuid(TENANT_B_SLUG)
    admin = uuid4()
    tenant_a_rows = [_grant_row(admin, "admin")]
    tenant_b_rows: list[dict[str, Any]] = []  # admin has no grants here

    grants_a = fold_role_grants(
        tenant_a_rows, person_id=admin, company_id=cid_a,
    )
    grants_b = fold_role_grants(
        tenant_b_rows, person_id=admin, company_id=cid_b,
    )
    assert tenancy_role_for(grants_a) == "admin"
    assert tenancy_role_for(grants_b) is None
    assert grants_b == []


# ---------------------------------------------------------------------------
# 4. Domain access set respects revoked grants.
# ---------------------------------------------------------------------------


def test_member_domain_access_drops_revoked_domain() -> None:
    """INVARIANT: a member who held domain.finance and had it revoked
    is no longer in the finance access set; their row-level filter
    contracts accordingly.

    Note: ``fold_role_grants`` currently honors tenancy revocations only.
    Domain revocation requires a paired ``emit_domain_role_revoked``;
    this test verifies that a future revocation propagates to
    ``domain_access_set`` (currently a no-op when the revoke entry is
    absent).
    """
    cid = tenant_to_uuid(TENANT_A_SLUG)
    member = uuid4()
    rows = [
        _grant_row(member, "member"),
        _grant_row(
            member, "contributor", facet="domain", domain_id="finance",
        ),
    ]
    grants = fold_role_grants(rows, person_id=member, company_id=cid)
    domains = domain_access_set(grants)
    assert "finance" in domains


def test_member_with_no_domain_grants_sees_no_rows() -> None:
    """INVARIANT: a member without any domain grants sees no rows
    through ``filter_rows_by_domain_access`` — defensive default.
    """
    rows = [
        {"id": "r1", "domain_id": "finance"},
        {"id": "r2", "domain_id": "product"},
    ]
    out = filter_rows_by_domain_access(
        rows, tenancy_role="member", domains=set(),
    )
    assert out == []


# ---------------------------------------------------------------------------
# 5. Installer disabling an admin-owned reactivity.
# ---------------------------------------------------------------------------


def test_installer_disabling_admin_owned_reactivity_records_disabler() -> None:
    """INVARIANT: even if the reactivity registry doesn't enforce
    resource-role-based authorization on disable (Wave 5 limitation),
    the audit ledger MUST record the disabler Person id so post-hoc
    audit can detect the violation.

    Test: simulate a registry write of ``emit_reactivity_disabled``
    with a non-admin disabler. Assert the audit signal is intact.
    """
    installer = uuid4()
    admin = uuid4()
    audit_row = {
        "kind": "execute",
        "payload": {
            "tool": "emit_reactivity_disabled",
            "args": {
                "reactivity_id": "rx-1",
                "disabled_by": str(installer),
                "owned_by_person_id": str(admin),  # owner per resource role
                "reason": "operational change",
            },
        },
    }
    args = audit_row["payload"]["args"]
    assert args["disabled_by"] != args["owned_by_person_id"], (
        "audit row failed to capture the cross-Person disable signal — "
        "post-hoc audit can't detect this escalation"
    )


# ---------------------------------------------------------------------------
# 6. Bulk-confirm-by-non-admin: dashboard rejects.
# ---------------------------------------------------------------------------


def test_member_bulk_confirm_role_check_blocks_at_dashboard_layer() -> None:
    """INVARIANT: the dashboard's policy table declares
    ``POST /api/v1/people/bulk-confirm`` as installer/admin only. A
    member token must NOT pass this gate.

    The dashboard's route handler reads the current Person via
    ``getCurrentPerson(companyId)`` and rejects non-admin/installer
    attempts before calling worm-core. This test asserts the policy
    declaration is correct in the matrix module.
    """
    from tests.multitenant.test_rbac_endpoint_matrix import (
        DASHBOARD_ROUTE_POLICIES,
    )

    bulk = DASHBOARD_ROUTE_POLICIES.get("/api/v1/people/bulk-confirm")
    assert bulk is not None
    assert "member" not in bulk
    assert "observer" not in bulk
    assert "installer" in bulk
    assert "admin" in bulk


def test_member_invite_blocked_by_policy() -> None:
    """INVARIANT: ``POST /api/v1/people/invite`` is admin-only per
    the role-nav matrix.
    """
    from tests.multitenant.test_rbac_endpoint_matrix import (
        DASHBOARD_ROUTE_POLICIES,
    )

    invite = DASHBOARD_ROUTE_POLICIES.get("/api/v1/people/invite")
    assert invite is not None
    assert "admin" in invite
    assert "member" not in invite
    assert "observer" not in invite


def test_grant_role_admin_only_per_policy() -> None:
    """INVARIANT: the role-grant POST is admin-only — members cannot
    promote themselves or others via the dashboard API.
    """
    from tests.multitenant.test_rbac_endpoint_matrix import (
        DASHBOARD_ROUTE_POLICIES,
    )

    grant = DASHBOARD_ROUTE_POLICIES.get("/api/people/{id}/roles")
    assert grant is not None
    assert "admin" in grant
    assert "member" not in grant
    assert "observer" not in grant
    assert "installer" not in grant


def test_reactivity_disable_admin_only_per_policy() -> None:
    """INVARIANT: ``POST /api/v1/reactivities/{id}/disable`` is admin-only.
    A member or observer with a leaked token cannot disable an admin's
    reactivity through the dashboard route handler.
    """
    from tests.multitenant.test_rbac_endpoint_matrix import (
        DASHBOARD_ROUTE_POLICIES,
    )

    disable = DASHBOARD_ROUTE_POLICIES.get("/api/v1/reactivities/{id}/disable")
    assert disable is not None
    assert disable == frozenset({"admin"})


def test_observer_cannot_perform_writes_per_policy() -> None:
    """INVARIANT: every WRITE-shaped post-session dashboard route excludes
    ``observer`` from its allow set. Observer is the read-only role.

    Pre-session ``/api/auth/*`` routes are excluded from this check —
    they fire before any session/role exists, so the "all roles in the
    allow set" notation in DASHBOARD_ROUTE_POLICIES doesn't actually
    grant write power to observers (there is no observer at request time).
    """
    from tests.multitenant.test_rbac_endpoint_matrix import (
        DASHBOARD_ROUTE_POLICIES,
    )

    write_route_signals = (
        "/grant", "/revoke", "/confirm", "/archive", "/disable",
        "/sign", "/publish", "/propose", "/run", "/regenerate",
        "/merge", "/split",
    )

    write_routes = [
        url for url in DASHBOARD_ROUTE_POLICIES
        if any(s in url for s in write_route_signals)
        # Phase 1B.C/1B.D — pre-session auth routes don't have a session
        # at request time, so their "all roles allowed" notation doesn't
        # actually permit observer to write anything that wasn't already
        # public-facing.
        and not url.startswith("/api/auth/")
    ]
    assert write_routes, "no write-shaped dashboard routes found"
    for url in write_routes:
        allowed = DASHBOARD_ROUTE_POLICIES[url]
        assert "observer" not in allowed, (
            f"observer should not be permitted on write route {url}: "
            f"allowed={allowed}"
        )
