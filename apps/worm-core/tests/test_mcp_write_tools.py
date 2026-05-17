"""Tests for the MCP write tools (J2).

Three tools:

- ``propose_data_product``
- ``confirm_proposal``
- ``propose_kpi``

Each requires ``tenancy.admin``. Tests cover:

- happy-path admin invocation (each tool)
- permission-denied for non-admin / no-token caller
- audit entry written on every call (ok or denied)
- proposal-id resolution for confirm_proposal (data_product + person paths)
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.mcp_tools.auth import encode_compact_token
from wormbase_core.mcp_tools.write_tools import WRITE_TOOL_NAMES
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-j2"
TENANT_SLUG = "baseworm"


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


def _ctx_with_token(token: str):
    class _H:
        def __init__(self, t: str) -> None:
            self.t = t

        def get(self, k: str) -> str | None:
            if k.lower() == "authorization":
                return f"Bearer {self.t}"
            return None

    class _Req:
        headers = _H(token)

    class _RC:
        request = _Req()

    class _Ctx:
        request_context = _RC()

    return _Ctx()


def _admin_token(person: UUID) -> str:
    return encode_compact_token(
        secret=API_TOKEN, person_id=person, tenant_slug=TENANT_SLUG,
    )


async def _drive(mcp, tool_name: str, ctx, **kwargs):
    tm = mcp._tool_manager  # noqa: SLF001
    tool_obj = tm.get_tool(tool_name)
    return await tool_obj.fn(ctx=ctx, **kwargs)


async def _seed_person_row(ledger: InMemoryLedger, person: UUID) -> None:
    """Seed an emit_person_proposed entry so the 1B.F authorize_caller
    gate sees the Person row exist in this tenant.

    Phase 1B.F adds a binding gate that rejects tokens whose person_id
    has no Person row in projection_persons for the bound tenant; tests
    that previously only seeded role grants must now also seed the
    Person row.
    """
    args = {
        "person_id": str(person),
        "tenant_id": str(_company_id()),
        "name": "Test Person",
        "email": f"{person}@test.invalid",
        "proposed_by": "test",
    }
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "person_proposed", "ref_id": str(person),
            "reason": "seed person row for 1B.F gate", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed", "args": args,
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _grant_admin(ledger: InMemoryLedger, person: UUID) -> None:
    """Seed an emit_role_assigned grant for tenancy.admin.

    Also seeds the Person row first so the 1B.F authorize_caller gate
    accepts the token; admin tokens must point at a real Person.
    """
    await _seed_person_row(ledger, person)
    args = {
        "person_id": str(person),
        "role": "admin",
        "granted_by": str(person),
    }
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "role_assigned", "ref_id": str(uuid4()),
            "reason": "seed admin", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_role_assigned", "args": args,
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _seed_proposed_person(ledger: InMemoryLedger) -> str:
    pid = str(uuid4())
    args = {
        "person_id": pid,
        "tenant_id": str(_company_id()),
        "name": "Carol",
        "email": "carol@example.com",
        "proposed_by": "test",
    }
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "person_proposed", "ref_id": pid,
            "reason": "seed", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed", "args": args,
            "result_ref": pid,
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )
    return pid


@pytest.fixture
def mcp_server():
    ledger = InMemoryLedger()
    mcp = build_mcp_server(ledger=ledger, api_token=API_TOKEN)
    return mcp, ledger


# -------------------------------------------------------------------
# Sanity: tools registered.
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_all_write_tools_registered(mcp_server) -> None:
    mcp, _ = mcp_server
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    for tool_name in WRITE_TOOL_NAMES:
        assert tool_name in names


# -------------------------------------------------------------------
# Happy-path tests.
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_data_product_happy_admin(mcp_server) -> None:
    mcp, ledger = mcp_server
    admin = uuid4()
    await _grant_admin(ledger, admin)
    ctx = _ctx_with_token(_admin_token(admin))
    out = await _drive(
        mcp, "propose_data_product", ctx,
        company_id=TENANT_SLUG, name="Q3 chart", kind="chart",
        parameters={"x": "month", "y": "revenue"},
    )
    assert out["status"] == "proposed"
    assert "data_product_id" in out

    # Verify the propose ledger entry landed (tool call PEVR + propose PEVR).
    rows = await ledger.fetch(_company_id())
    proposed_kinds = [
        r["payload"]["tool"] for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_data_product_proposed" in proposed_kinds


@pytest.mark.asyncio
async def test_propose_kpi_happy_admin(mcp_server) -> None:
    mcp, ledger = mcp_server
    admin = uuid4()
    await _grant_admin(ledger, admin)
    ctx = _ctx_with_token(_admin_token(admin))
    out = await _drive(
        mcp, "propose_kpi", ctx,
        company_id=TENANT_SLUG, name="Net Revenue Q3",
    )
    assert out["status"] == "proposed"
    assert "kpi_id" in out

    rows = await ledger.fetch(_company_id())
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_kpi_proposed" in tools


@pytest.mark.asyncio
async def test_confirm_proposal_resolves_person(mcp_server) -> None:
    mcp, ledger = mcp_server
    admin = uuid4()
    await _grant_admin(ledger, admin)
    proposed_pid = await _seed_proposed_person(ledger)
    ctx = _ctx_with_token(_admin_token(admin))
    out = await _drive(
        mcp, "confirm_proposal", ctx,
        company_id=TENANT_SLUG,
        proposal_id=proposed_pid,
        person_id=str(admin),
    )
    assert out["proposal_id"] == proposed_pid
    assert out["kind"] == "person_confirmed"

    # The person_confirmed ledger entry landed.
    rows = await ledger.fetch(_company_id())
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_person_confirmed" in tools


@pytest.mark.asyncio
async def test_confirm_proposal_acknowledges_data_product(mcp_server) -> None:
    mcp, ledger = mcp_server
    admin = uuid4()
    await _grant_admin(ledger, admin)
    ctx = _ctx_with_token(_admin_token(admin))
    # Seed a data product proposal first via the MCP write tool.
    proposed = await _drive(
        mcp, "propose_data_product", ctx,
        company_id=TENANT_SLUG, name="X", kind="chart",
    )
    out = await _drive(
        mcp, "confirm_proposal", ctx,
        company_id=TENANT_SLUG,
        proposal_id=proposed["data_product_id"],
        person_id=str(admin),
    )
    assert out["kind"] == "data_product_proposed_acknowledged"


# -------------------------------------------------------------------
# Permission denied tests.
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_data_product_denied_for_member(mcp_server) -> None:
    mcp, ledger = mcp_server
    member = uuid4()
    # Phase 1B.F: seed Person row so the binding gate accepts the token.
    await _seed_person_row(ledger, member)
    # Grant only tenancy.member, NOT admin.
    args = {
        "person_id": str(member),
        "role": "member",
        "granted_by": str(member),
    }
    await ledger.write(
        company_id=_company_id(),
        propose={
            "target_kind": "role_assigned", "ref_id": str(uuid4()),
            "reason": "seed", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_role_assigned", "args": args,
            "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )

    ctx = _ctx_with_token(_admin_token(member))
    with pytest.raises(PermissionError, match="requires tenancy.admin"):
        await _drive(
            mcp, "propose_data_product", ctx,
            company_id=TENANT_SLUG, name="X", kind="chart",
        )

    # Denied audit entry must have landed.
    rows = await ledger.fetch(_company_id())
    audit_args = [
        r["payload"]["args"] for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_mcp_call_received"
    ]
    assert any(a["outcome"] == "denied" for a in audit_args)


@pytest.mark.asyncio
async def test_propose_kpi_denied_for_no_token(mcp_server) -> None:
    mcp, _ = mcp_server
    # Empty bearer token → PermissionError.

    class _Empty:
        def get(self, k: str) -> str | None:
            return None

    class _Req:
        headers = _Empty()

    class _RC:
        request = _Req()

    class _Ctx:
        request_context = _RC()

    with pytest.raises(PermissionError):
        await _drive(
            mcp, "propose_kpi", _Ctx(),
            company_id=TENANT_SLUG, name="X",
        )
