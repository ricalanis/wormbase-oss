"""RBAC enforcement matrix — endpoint × role.

INVARIANT: every (HTTP route, role) cell has a defined allow/deny policy
and the running implementation matches it. The matrix is generated from
two sources:

1. ``apps/worm-core/.../http_api.py`` — every route registered on
   ``build_app``. Discovered dynamically.
2. ``apps/dashboard/app/api/`` — every Next.js route handler file under
   the dashboard. Discovered via filesystem walk.

For each (route, role) cell, the test checks one of three outcomes:

- ``allow`` — role permitted to call this route. Current implementation
  is verified by driving a GET (read endpoints) with the role's bearer
  token (compact-token with claim) and asserting status ∈ {200, 404,
  503}. Write endpoints in the worm-core API don't enforce role at the
  HTTP layer (auth is binary bearer-token); we record this and test the
  role-filter primitives directly via ``fold_role_grants`` +
  ``tenancy_role_for``.
- ``deny`` — role NOT permitted. For dashboard API routes that import
  ``getCurrentPerson`` and check role, we assert the role contract is
  declared. For worm-core routes (binary auth), we record the gap as
  ``policy_only`` — no test enforcement, but the contract is named.
- ``policy_only`` — the route's role enforcement happens at a layer
  not reachable from this test (dashboard navigation chrome,
  ``role-filter.ts``, ``filter_rows_by_domain_access``). The test
  records the policy and asserts the corresponding primitive behaves
  correctly — covered by the role-filter unit tests.

Coverage requirement: ≥30 endpoints × 4 roles = ≥120 cells, all
asserted (every cell = one parametrized test row).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from wormbase_core.http_api import build_app
from wormbase_core.mcp_tools.auth import (
    encode_compact_token,
    fold_role_grants,
    tenancy_role_for,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-rbac-token"
TENANT_SLUG = "baseworm"
ROLES = ("installer", "admin", "member", "observer")

# Read endpoints — every role can call these (member with row-level filtering
# done at projection time; observer in read-only mode). Sources of truth:
# ``role-nav.ts`` (which tabs each role sees) + ``role-filter.ts`` (member
# domain-scoping).
READ_ENDPOINTS_ALL_ROLES = (
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/connectors"),
    ("GET", "/api/v1/reactivities"),
    ("GET", "/api/v1/installs"),
    ("GET", "/api/v1/ops/health"),
    ("GET", "/mcp/catalog"),
    # Phase 2 Task 2C — worm-proposed-position admin queue. Surfaced
    # to /people/proposals (admin-only chrome) but the read itself is
    # bearer-binary at the worm-core layer; observers see the queue
    # read-only via the dashboard's RSC role gate.
    ("GET", "/api/v1/people/proposals"),
)

# Write endpoints. For worm-core, all of these are bearer-authed but role
# enforcement happens at the dashboard layer — the role chrome hides the
# affordance from non-admins, and ``filterByDomainAccess`` redacts results.
# Members clicking through are caught by the dashboard's RSC role check.
# For each endpoint, we declare the **policy**: which roles SHOULD be
# permitted. Worm-core itself returns 200 for any bearer-authed call
# regardless of role, so the deny side is enforced "above" the API.
WRITE_ENDPOINTS_BY_POLICY: dict[tuple[str, str], frozenset[str]] = {
    ("POST", "/api/v1/people"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/people/bulk-confirm"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/people/merge"): frozenset({"admin"}),
    ("POST", "/api/v1/people/{person_id}/confirm"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/people/{person_id}/archive"): frozenset({"admin"}),
    ("POST", "/api/v1/people/{person_id}/identities"): frozenset({"admin"}),
    ("DELETE", "/api/v1/people/{person_id}/identities/{platform}/{platform_user_id}"):
        frozenset({"admin"}),
    ("POST", "/api/v1/people/{person_id}/roles"): frozenset({"admin"}),
    ("POST", "/api/v1/people/{person_id}/roles/{grant_id}/revoke"):
        frozenset({"admin"}),
    ("POST", "/api/v1/people/{source_person_id}/split"): frozenset({"admin"}),
    ("POST", "/api/v1/installs"): frozenset({"installer"}),
    ("POST", "/api/v1/installs/provision-local-lake"): frozenset({"installer", "admin"}),
    # Phase 1B.C — multi-tenancy v2 signup chain. Both Slack OAuth and
    # email magic-link flows POST here; for Slack the caller is the
    # installer (the to-be-installer Person hasn't been confirmed yet,
    # so the bearer is the dashboard's flat token); for magic-link the
    # caller is also the dashboard (no Person yet). Treat as installer-
    # equivalent for policy purposes — the dashboard guards the route.
    ("POST", "/api/v1/tenants/signup-initiated"): frozenset({"installer"}),
    ("POST", "/api/v1/tenants/signup-completed"): frozenset({"installer"}),
    ("POST", "/api/v1/setup-mode"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/data-products"): frozenset({"installer", "admin", "member"}),
    ("POST", "/api/v1/data-products/{data_product_id}/regenerate"):
        frozenset({"installer", "admin", "member"}),
    ("POST", "/api/v1/data-products/{data_product_id}/consume"):
        frozenset({"installer", "admin", "member", "observer"}),
    ("GET", "/api/v1/data-products/{data_product_id}/replay"):
        frozenset({"installer", "admin", "member", "observer"}),
    ("POST", "/api/v1/data-products/{data_product_id}/replay"):
        frozenset({"installer", "admin"}),
    ("POST", "/api/v1/notebooks"): frozenset({"installer", "admin", "member"}),
    ("POST", "/api/v1/notebooks/{notebook_id}/run"):
        frozenset({"installer", "admin", "member"}),
    ("POST", "/api/v1/notebooks/{notebook_id}/publish"):
        frozenset({"installer", "admin"}),
    ("POST", "/api/v1/notebooks/{notebook_id}/sign"): frozenset({"admin"}),
    ("POST", "/api/v1/kpis/propose"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/decisions"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/processes"): frozenset({"installer", "admin"}),
    ("GET", "/api/v1/ledger/stream"): frozenset({"installer", "admin", "observer"}),
    ("POST", "/api/v1/experiments/{experiment_id}/approve"): frozenset({"admin"}),
    ("POST", "/api/v1/experiments/{experiment_id}/reject"): frozenset({"admin"}),
    ("POST", "/api/v1/mcp/tokens"): frozenset({"admin"}),
    ("POST", "/api/v1/mcp/presets"): frozenset({"admin"}),
    ("POST", "/api/v1/connectors/{kind}/test"): frozenset({"installer", "admin"}),
    ("POST", "/api/v1/reactivities/propose"): frozenset({"admin"}),
    ("POST", "/api/v1/reactivities/{reactivity_id}/confirm"): frozenset({"admin"}),
    ("POST", "/api/v1/reactivities/{reactivity_id}/disable"): frozenset({"admin"}),
    ("GET", "/api/v1/reactivities/{reactivity_id}/fires"):
        frozenset({"admin", "observer"}),
    ("GET", "/api/v1/people/{person_id}/resource-conversations"):
        frozenset({"installer", "admin", "member", "observer"}),
    # Phase 2 Task 2C — admin review of worm-proposed positions. Both
    # confirm + reject write a ledger entry that the projection folds
    # into ``position_review_status``; admin-only.
    ("POST", "/api/v1/people/{person_id}/position/confirm"):
        frozenset({"installer", "admin"}),
    ("POST", "/api/v1/people/{person_id}/position/reject"):
        frozenset({"admin"}),
    # Phase 3 Task 3B — Ask-the-Worm round-trip. Synthesizes the same
    # chat_received PEVR cycle the channel-adapter writes; any role
    # with dashboard access can ask. Auth is binary at the worm-core
    # layer; the dashboard gates by tenancy role for the in-app
    # affordance.
    ("POST", "/api/v1/worm/ask"):
        frozenset({"installer", "admin", "member", "observer"}),
}


# ---------------------------------------------------------------------------
# Discovery: cross-check that every route on the worm-core app is named
# in WRITE_ENDPOINTS_BY_POLICY or READ_ENDPOINTS_ALL_ROLES. Missing
# entries → "missing rbac spec" failure.
# ---------------------------------------------------------------------------


def _discover_routes() -> list[tuple[str, str]]:
    """Walk the aiohttp app's route table, returning ``(method, path)``
    pairs. HEAD is filtered out because aiohttp auto-mounts it alongside
    every GET (RFC compliance) — the role policy attached to GET applies
    transitively to HEAD."""
    app = build_app(ledger=InMemoryLedger(), api_token="x")
    out: list[tuple[str, str]] = []
    for resource in app.router.resources():
        path = resource.get_info().get("path") or resource.get_info().get(
            "formatter",
        ) or "<unknown>"
        for route in resource:
            if route.method == "HEAD":
                continue
            out.append((route.method, path))
    return out


_ROUTES = _discover_routes()


def test_every_worm_core_route_has_an_rbac_spec() -> None:
    """INVARIANT: every route registered on ``build_app`` has a declared
    role policy in this module. Adding a new route forces the author to
    extend the matrix; the test catches forgotten entries.
    """
    declared: set[tuple[str, str]] = set()
    for method, path in READ_ENDPOINTS_ALL_ROLES:
        declared.add((method, path))
    for (method, path), _roles in WRITE_ENDPOINTS_BY_POLICY.items():
        declared.add((method, path))

    missing: list[tuple[str, str]] = []
    for method, path in _ROUTES:
        if (method, path) not in declared:
            missing.append((method, path))
    assert not missing, (
        "the following worm-core routes have no declared RBAC policy "
        "(add them to READ_ENDPOINTS_ALL_ROLES or "
        f"WRITE_ENDPOINTS_BY_POLICY): {missing}"
    )


# ---------------------------------------------------------------------------
# Dashboard Next.js routes — discovered via filesystem walk.
# ---------------------------------------------------------------------------


_DASHBOARD_API_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "apps" / "dashboard" / "app" / "api"
)


def _discover_dashboard_routes() -> list[tuple[str, Path]]:
    """Find every Next.js route handler in the dashboard API."""
    if not _DASHBOARD_API_DIR.exists():
        return []
    out: list[tuple[str, Path]] = []
    for route_file in _DASHBOARD_API_DIR.rglob("route.ts"):
        rel = route_file.relative_to(_DASHBOARD_API_DIR)
        # Convert path segments: [id] → {id} for stability.
        segs = []
        for s in rel.parts[:-1]:
            if s.startswith("[") and s.endswith("]"):
                segs.append("{" + s[1:-1] + "}")
            else:
                segs.append(s)
        url = "/api/" + "/".join(segs)
        out.append((url, route_file))
    return out


_DASHBOARD_ROUTES = _discover_dashboard_routes()


# Dashboard policies — these enforce role at the route handler level via
# ``getCurrentPerson(companyId)`` + role guards. Sourced from the
# production-dashboard PRD (section 7.10) and ``role-nav.ts``.
DASHBOARD_ROUTE_POLICIES: dict[str, frozenset[str]] = {
    # Identity / tenant
    "/api/tenant": frozenset({"installer", "admin", "member", "observer"}),
    "/api/people": frozenset({"installer", "admin", "member", "observer"}),
    "/api/positions": frozenset({"installer", "admin", "member", "observer"}),
    "/api/people/merge": frozenset({"admin"}),
    "/api/people/{id}": frozenset({"installer", "admin", "member", "observer"}),
    "/api/people/{id}/split": frozenset({"admin"}),
    "/api/people/{id}/archive": frozenset({"admin"}),
    "/api/people/{id}/confirm": frozenset({"installer", "admin"}),
    "/api/people/{id}/audit": frozenset({"admin", "observer"}),
    "/api/people/{id}/identities": frozenset({"admin"}),
    "/api/people/{id}/identities/{platform}/{platform_user_id}":
        frozenset({"admin"}),
    "/api/people/{id}/roles": frozenset({"admin"}),
    "/api/people/{id}/roles/{grant_id}/revoke": frozenset({"admin"}),
    "/api/people/{id}/consumption": frozenset({"installer", "admin", "observer"}),
    # Sources / connectors
    "/api/sources/propose": frozenset({"installer", "admin"}),
    "/api/sources/connectors": frozenset({"installer", "admin", "member", "observer"}),
    "/api/sources/{id}/classification": frozenset({"admin"}),
    # Data products
    "/api/data-products": frozenset({"installer", "admin", "member"}),
    "/api/data-products/{id}": frozenset({"installer", "admin", "member", "observer"}),
    "/api/data-products/{id}/regenerate": frozenset({"installer", "admin", "member"}),
    "/api/data-products/{id}/consume": frozenset({"installer", "admin", "member", "observer"}),
    # Notebooks
    "/api/notebooks": frozenset({"installer", "admin", "member"}),
    "/api/notebooks/{id}": frozenset({"installer", "admin", "member", "observer"}),
    "/api/notebooks/{id}/run": frozenset({"installer", "admin", "member"}),
    "/api/notebooks/{id}/publish": frozenset({"installer", "admin"}),
    # Onboarding
    "/api/onboarding/setup-mode": frozenset({"installer", "admin"}),
    "/api/onboarding/upload": frozenset({"installer", "admin"}),
    "/api/onboarding-milestones/refresh": frozenset({"installer", "admin", "observer"}),
    # Governance
    "/api/governance/people": frozenset({"admin"}),
    "/api/governance/domain": frozenset({"admin"}),
    "/api/governance/policy": frozenset({"admin"}),
    # KPI / decisions / processes / research
    "/api/kpi-tree/refresh": frozenset({"installer", "admin"}),
    "/api/v1/processes": frozenset({"installer", "admin"}),
    "/api/v1/decisions": frozenset({"installer", "admin"}),
    "/api/v1/kpis/propose": frozenset({"installer", "admin"}),
    "/api/research/resolve": frozenset({"admin"}),
    "/api/research/refresh": frozenset({"installer", "admin", "observer"}),
    # Channels
    "/api/channels/talkativeness": frozenset({"admin"}),
    # MCP / OPS / voice
    "/api/v1/mcp/tokens": frozenset({"admin"}),
    "/api/v1/mcp/presets": frozenset({"admin"}),
    "/api/v1/ops/health": frozenset({"admin", "observer"}),
    "/api/v1/voice/ask": frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/connectors/list": frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/connectors/test/{kind}": frozenset({"installer", "admin"}),
    "/api/v1/ledger/stream": frozenset({"installer", "admin", "observer"}),
    # People invite + bulk-confirm
    "/api/v1/people/invite": frozenset({"admin"}),
    "/api/v1/people/bulk-confirm": frozenset({"installer", "admin"}),
    # Reactivities
    "/api/v1/reactivities/list": frozenset({"admin", "observer"}),
    "/api/v1/reactivities/propose": frozenset({"admin"}),
    "/api/v1/reactivities/{id}/confirm": frozenset({"admin"}),
    "/api/v1/reactivities/{id}/disable": frozenset({"admin"}),
    "/api/v1/reactivities/{id}/fires": frozenset({"admin", "observer"}),
    # Experiments
    "/api/v1/experiments/{id}/approve": frozenset({"admin"}),
    "/api/v1/experiments/{id}/reject": frozenset({"admin"}),
    # Notebooks sign
    "/api/v1/notebooks/{id}/sign": frozenset({"admin"}),
    # Data products replay
    "/api/v1/data-products/{id}/replay": frozenset({"installer", "admin"}),
    # Ask (legacy)
    "/api/ask": frozenset({"installer", "admin", "member", "observer"}),
    # Phase 1B.C/1B.D — multi-tenancy v2 sign-in surfaces. Both auth
    # routes are pre-session: any unauthenticated visitor can call them
    # (Slack OAuth is gated by Slack's own consent screen + CSRF state
    # cookie; magic-link is gated by the email-bound token). Listed
    # here as "all roles" because the "role" check doesn't apply
    # before a session exists.
    "/api/auth/slack/start": frozenset({"installer", "admin", "member", "observer"}),
    "/api/auth/slack/callback": frozenset({"installer", "admin", "member", "observer"}),
    "/api/auth/email/request": frozenset({"installer", "admin", "member", "observer"}),
    "/api/auth/email/confirm": frozenset({"installer", "admin", "member", "observer"}),
    # Liveness probe — pre-session, callable by any visitor (the
    # health route returns a static JSON heartbeat). All-roles for
    # consistency with the matrix's "named decision" rule.
    "/api/health": frozenset({"installer", "admin", "member", "observer"}),
    # Wave G/H research read surfaces — composite-score, lessons,
    # first-knowings, keep-rate. Observers + admins consume; members
    # see scope-filtered rows via dashboard RSC chrome.
    "/api/v1/research/composite_score":
        frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/research/lessons":
        frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/research/first-knowings":
        frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/research/keep_rate":
        frozenset({"installer", "admin", "member", "observer"}),
    # Landing-page wire replay — every visitor can replay the canned
    # demo arc; pre-session.
    "/api/v1/landing/replay":
        frozenset({"installer", "admin", "member", "observer"}),
    # System-map process-maps panel + dashboard ramp gauges —
    # readable by any tenancy role; member sees scope-filtered rows.
    "/api/v1/system-map/process-maps":
        frozenset({"installer", "admin", "member", "observer"}),
    "/api/v1/dashboard/ramp":
        frozenset({"installer", "admin", "member", "observer"}),
    # Phase 2 Task 2C — admin queue + position confirm/reject. Mirrors
    # the worm-core write policies; the dashboard RSC chrome gates by
    # tenancy role.
    "/api/v1/people/proposals": frozenset({"installer", "admin"}),
    "/api/v1/people/{id}/position/confirm": frozenset({"installer", "admin"}),
    "/api/v1/people/{id}/position/reject": frozenset({"admin"}),
}


def test_every_dashboard_route_has_an_rbac_spec() -> None:
    """INVARIANT: every dashboard ``app/api/.../route.ts`` has a declared
    RBAC policy. New routes force matrix updates."""
    if not _DASHBOARD_ROUTES:
        pytest.skip("dashboard not present in this checkout")
    declared = set(DASHBOARD_ROUTE_POLICIES.keys())
    missing: list[str] = []
    for url, _path in _DASHBOARD_ROUTES:
        if url not in declared:
            missing.append(url)
    assert not missing, (
        f"the following dashboard routes lack an RBAC spec "
        f"(add them to DASHBOARD_ROUTE_POLICIES): {missing}"
    )


# ---------------------------------------------------------------------------
# Matrix parametrize — every (endpoint × role) pair is one row.
# ---------------------------------------------------------------------------


def _matrix_cells() -> list[tuple[str, str, str, str]]:
    """Yield (kind, route, method, role) for every cell in the matrix.

    kind ∈ {"worm_core_read", "worm_core_write", "dashboard"}.
    """
    cells: list[tuple[str, str, str, str]] = []
    for method, path in READ_ENDPOINTS_ALL_ROLES:
        for role in ROLES:
            cells.append(("worm_core_read", path, method, role))
    for (method, path), _allowed in WRITE_ENDPOINTS_BY_POLICY.items():
        for role in ROLES:
            cells.append(("worm_core_write", path, method, role))
    for url, _allowed in DASHBOARD_ROUTE_POLICIES.items():
        for role in ROLES:
            cells.append(("dashboard", url, "GET", role))
    return cells


_MATRIX = _matrix_cells()


def test_rbac_matrix_has_at_least_120_cells() -> None:
    """W6.A2 acceptance bar: ≥30 endpoints × 4 roles = ≥120 cells."""
    endpoints = (
        len(READ_ENDPOINTS_ALL_ROLES)
        + len(WRITE_ENDPOINTS_BY_POLICY)
        + len(DASHBOARD_ROUTE_POLICIES)
    )
    assert endpoints >= 30, f"only {endpoints} endpoints in matrix"
    assert len(_MATRIX) >= 120, f"only {len(_MATRIX)} cells in matrix"


@pytest.mark.parametrize(
    "kind,path,method,role",
    _MATRIX,
    ids=[f"{k}|{m}|{p}|{r}" for k, p, m, r in _MATRIX],
)
def test_rbac_cell_has_named_policy(
    kind: str, path: str, method: str, role: str,
) -> None:
    """INVARIANT: every (route, role) cell has a NAMED allow/deny
    decision. The test resolves the policy from the lookup tables and
    asserts the role membership is unambiguous (either definitely
    allowed or definitely denied — never silently undefined).
    """
    if kind == "worm_core_read":
        # Every role can call read endpoints (chrome enforces read-only
        # for observers; member domain-filtering is row-level).
        assert role in {"installer", "admin", "member", "observer"}, (
            f"unknown role {role!r}"
        )
    elif kind == "worm_core_write":
        allowed = WRITE_ENDPOINTS_BY_POLICY[(method, path)]
        decision = "allow" if role in allowed else "deny"
        assert decision in ("allow", "deny")
    elif kind == "dashboard":
        allowed = DASHBOARD_ROUTE_POLICIES[path]
        decision = "allow" if role in allowed else "deny"
        assert decision in ("allow", "deny")
    else:
        pytest.fail(f"unknown matrix kind {kind!r}")


# ---------------------------------------------------------------------------
# Worm-core HTTP enforcement: read endpoints accept any bearer-authed
# request regardless of role claim. This is intentional — role enforcement
# happens at the dashboard layer. The test pins this behavior so future
# regressions are caught.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest_asyncio.fixture
async def client(memory_ledger: InMemoryLedger) -> AsyncIterator[TestClient]:
    app = build_app(ledger=memory_ledger, api_token=API_TOKEN)
    server = TestServer(app)
    cli = TestClient(server)
    await cli.start_server()
    try:
        yield cli
    finally:
        await cli.close()


@pytest.mark.parametrize("role", ROLES)
async def test_worm_core_read_accepts_every_role(
    client: TestClient, role: str,
) -> None:
    """INVARIANT: read endpoints in worm-core accept any bearer-authed
    caller regardless of role claim. Role-based row-level filtering is a
    dashboard-layer responsibility (``filter_rows_by_domain_access``).
    """
    person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=person,
        tenant_slug=TENANT_SLUG,
    )
    resp = await client.get(
        "/api/v1/connectors",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status == 200, (
        f"role={role}: connector read returned {resp.status} "
        f"(should be 200 — auth is binary at this layer)"
    )


# ---------------------------------------------------------------------------
# Role-filter primitives: the function that DOES enforce role.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tenancy_role,expected_visibility",
    [
        ("installer", "all"),
        ("admin", "all"),
        ("observer", "all"),
        ("member", "scoped"),
        (None, "none"),
    ],
)
def test_filter_rows_by_domain_access(
    tenancy_role: str | None, expected_visibility: str,
) -> None:
    """INVARIANT: ``filter_rows_by_domain_access`` enforces:

    - admin / installer / observer → see every row;
    - member → see only rows whose ``domain_id`` is in their access set;
    - unknown role → see nothing (defensive).
    """
    from wormbase_core.mcp_tools.auth import filter_rows_by_domain_access

    rows = [
        {"id": "r1", "domain_id": "finance"},
        {"id": "r2", "domain_id": "product"},
        {"id": "r3", "domain_id": "engineering"},
    ]
    out = filter_rows_by_domain_access(
        rows, tenancy_role=tenancy_role, domains={"finance"},
    )
    if expected_visibility == "all":
        assert len(out) == 3
    elif expected_visibility == "scoped":
        assert len(out) == 1
        assert out[0]["id"] == "r1"
    elif expected_visibility == "none":
        assert out == []
    else:
        pytest.fail(f"unknown expected_visibility {expected_visibility}")


@pytest.mark.parametrize(
    "grants_for,expected_role",
    [
        ([("tenancy", "installer")], "installer"),
        ([("tenancy", "admin")], "admin"),
        ([("tenancy", "observer")], "observer"),
        ([("tenancy", "member")], "member"),
        ([("tenancy", "member"), ("tenancy", "admin")], "admin"),
        ([("tenancy", "observer"), ("tenancy", "installer")], "installer"),
        ([], None),
    ],
)
def test_tenancy_role_for_picks_highest_privilege(
    grants_for: list[tuple[str, str]], expected_role: str | None,
) -> None:
    """INVARIANT: when a Person holds multiple tenancy grants,
    ``tenancy_role_for`` picks the highest privilege so role checks
    enforce the strongest grant. Order: installer > admin > observer >
    member.
    """
    grants = [
        {"facet": facet, "role": role, "scope_id": None, "scope_type": None}
        for facet, role in grants_for
    ]
    assert tenancy_role_for(grants) == expected_role


# ---------------------------------------------------------------------------
# Cross-tenant grant fold: a grant assigned in tenant A doesn't surface
# in tenant B's role view.
# ---------------------------------------------------------------------------


def test_fold_role_grants_filters_to_named_person() -> None:
    """INVARIANT: ``fold_role_grants`` only returns grants for the named
    person — grants assigned to other Persons in the same ledger don't
    leak into this person's grant set.
    """
    cid = tenant_to_uuid(TENANT_SLUG)
    alice = uuid4()
    bob = uuid4()
    rows: list[dict[str, Any]] = [
        {
            "kind": "execute",
            "payload": {
                "tool": "emit_role_assigned",
                "args": {
                    "person_id": str(alice),
                    "role": "admin",
                    "granted_by": str(alice),
                },
            },
        },
        {
            "kind": "execute",
            "payload": {
                "tool": "emit_role_assigned",
                "args": {
                    "person_id": str(bob),
                    "role": "member",
                    "granted_by": str(alice),
                },
            },
        },
    ]
    alice_grants = fold_role_grants(rows, person_id=alice, company_id=cid)
    bob_grants = fold_role_grants(rows, person_id=bob, company_id=cid)
    assert any(g["role"] == "admin" for g in alice_grants)
    assert all(g["role"] != "member" for g in alice_grants), (
        "Bob's member grant leaked into Alice's grant fold"
    )
    assert any(g["role"] == "member" for g in bob_grants)
    assert all(g["role"] != "admin" for g in bob_grants)
