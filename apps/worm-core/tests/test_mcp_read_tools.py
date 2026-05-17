"""Tests for the MCP read tools (J1).

Each tool gets one happy-path test that exercises the fold + role-aware
filter + audit pipeline through the FastMCP in-process API. We don't
boot the Streamable HTTP transport here — that's covered by the
existing ``test_mcp_server_e2e.py``. Instead, we drive the tool
functions directly via ``mcp.call_tool`` and assert on:

- the response shape;
- a ``mcp_call_received`` audit entry landed on the ledger.

Role-aware filter is sampled across member / admin / observer roles
in ``test_role_aware_filter_*`` tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.mcp_tools.auth import encode_compact_token
from wormbase_core.mcp_tools.read_tools import READ_TOOL_NAMES
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-j1"
TENANT_SLUG = "baseworm"


# -------------------------------------------------------------------
# Helpers (defined first so all tests can use them).
# -------------------------------------------------------------------


def _token_for(person_id: UUID, tenant_slug: str = TENANT_SLUG) -> str:
    return encode_compact_token(
        secret=API_TOKEN,
        person_id=person_id,
        tenant_slug=tenant_slug,
    )


def _ctx_with_token(token: str):
    """Build a fake Context-like object with a Bearer token header."""

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


async def _drive_tool_with_ctx(mcp, name: str, ctx, **kwargs):
    """Invoke a registered tool with an explicit Context.

    FastMCP's ``call_tool`` does not let you inject a Context; we
    reach through the tool manager and call the registered fn
    directly. The fn signature for our read tools accepts
    ``ctx=Context`` as a kwarg.
    """
    tm = mcp._tool_manager  # noqa: SLF001
    tool_obj = tm.get_tool(name)
    fn = tool_obj.fn
    return await fn(ctx=ctx, **kwargs)


def _extract_result(out: Any) -> Any:
    """The driven tool returns its raw return value (no conversion)."""
    return out


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


async def _seed_kpi(ledger: InMemoryLedger, *, name: str, domain: UUID | None = None) -> str:
    kid = str(uuid4())
    args = {"id": kid, "name": name}
    if domain is not None:
        args["domain_id"] = str(domain)
    await _write_execute(ledger, "emit_kpi_node", args)
    return kid


async def _seed_decision(
    ledger: InMemoryLedger, *, text: str = "ship friday",
    domain: str | None = None,
) -> str:
    did = str(uuid4())
    now = datetime.now(tz=UTC)
    args: dict[str, Any] = {
        "decision_id": did,
        "decision_text": text,
        "decision_at": now.isoformat(),
        "channel_id": "C-finance",
        "decided_by_persons": [str(uuid4())],
        "evidence_message_ids": ["m1", "m2"],
        "confidence": 0.8,
    }
    if domain is not None:
        args["domain_id"] = domain
    await _write_execute(ledger, "emit_decision_recorded", args)
    return did


async def _seed_process(
    ledger: InMemoryLedger, *, name: str = "q3 close",
    domain: str = "finance",
) -> str:
    pid = str(uuid4())
    args = {
        "process_id": pid,
        "process_name": name,
        "domain": domain,
        "steps": [
            {"order": 1, "actor": "Bob", "action": "export", "source_message_id": "m1"},
        ],
        "confidence": 0.7,
    }
    await _write_execute(ledger, "emit_process_map_proposed", args)
    return pid


async def _seed_recurring_question(ledger: InMemoryLedger) -> str:
    qid = str(uuid4())
    now = datetime.now(tz=UTC)
    args = {
        "question_id": qid,
        "normalized_question": "what is q3 revenue",
        "asked_by_persons": [str(uuid4())],
        "occurrences": 4,
        "first_seen_at": (now - timedelta(days=1)).isoformat(),
        "last_seen_at": now.isoformat(),
    }
    await _write_execute(ledger, "emit_recurring_question", args)
    return qid


async def _seed_system_node(ledger: InMemoryLedger) -> str:
    nid = "carol"
    args = {
        "node_kind": "person",
        "node_id": nid,
        "edges": [{"kind": "asks", "target_id": "alice", "weight": 0.6}],
    }
    await _write_execute(ledger, "emit_system_map_node", args)
    return nid


async def _seed_data_product(ledger: InMemoryLedger) -> str:
    dpid = str(uuid4())
    args = {
        "data_product_id": dpid,
        "name": "Revenue chart",
        "kind": "chart",
        "requested_by_person_id": str(uuid4()),
        "sources_required": [],
        "parameters": {},
    }
    await _write_execute(ledger, "emit_data_product_proposed", args)
    return dpid


async def _seed_notebook(ledger: InMemoryLedger, owner: UUID | None = None) -> str:
    nbid = str(uuid4())
    proposer = owner or uuid4()
    args = {
        "notebook_id": nbid,
        "name": "Q3 close",
        "cells": [],
        "kernel": "python",
        "proposed_by_person_id": str(proposer),
    }
    await _write_execute(ledger, "emit_notebook_proposed", args)
    return nbid


async def _seed_chat(
    ledger: InMemoryLedger, *,
    channel: str = "C-finance",
    classification: str = "internal",
) -> str:
    mid = f"m-{uuid4()}"
    args = {
        "channel_id": channel,
        "message_id": mid,
        "sender_person": str(uuid4()),
        "text": "What is Q3 revenue?",
        "classification": classification,
    }
    await _write_execute(ledger, "emit_chat_received", args)
    return mid


async def _seed_person(
    ledger: InMemoryLedger, *,
    name: str = "Carol",
    email: str = "carol@example.com",
) -> str:
    pid = str(uuid4())
    args = {
        "person_id": pid,
        "tenant_id": str(_company_id()),
        "name": name,
        "email": email,
        "proposed_by": "test",
    }
    await _write_execute(ledger, "emit_person_proposed", args)
    return pid


async def _seed_source(ledger: InMemoryLedger, *, kind: str = "file") -> str:
    sid = str(uuid4())
    args = {
        "source_id": sid,
        "source_kind": kind,
        "uri": "s3://demo/foo.csv",
        "added_via_flow": "drop_and_profile",
        "suggested_domain": "finance",
        "suggested_classification": "internal",
    }
    await _write_execute(ledger, "emit_source_proposed", args)
    return sid


async def _seed_person_row_for_token(
    ledger: InMemoryLedger, person_id: UUID,
) -> None:
    """Seed an emit_person_proposed entry so the 1B.F authorize_caller
    binding gate accepts a token claiming this person_id."""
    args = {
        "person_id": str(person_id),
        "tenant_id": str(_company_id()),
        "name": "Test Person",
        "email": f"{person_id}@test.invalid",
        "proposed_by": "test",
    }
    await _write_execute(ledger, "emit_person_proposed", args)


async def _seed_role_grant(
    ledger: InMemoryLedger, *,
    person_id: UUID,
    facet: str,
    role: str,
    domain_id: UUID | None = None,
) -> None:
    # Phase 1B.F: every role grant implies the Person exists. Seed the
    # Person row first so authorize_caller's binding gate accepts tokens
    # bound to this person_id. Idempotent at the ledger level — re-seeds
    # are append-only PEVR cycles and the gate just checks for one
    # proposed entry.
    await _seed_person_row_for_token(ledger, person_id)
    if facet == "tenancy":
        args = {
            "person_id": str(person_id),
            "role": role,
            "granted_by": str(person_id),
        }
        await _write_execute(ledger, "emit_role_assigned", args)
    elif facet == "domain":
        args = {
            "person_id": str(person_id),
            "role": role,
            "domain_id": str(domain_id),
            "granted_by": str(person_id),
        }
        await _write_execute(ledger, "emit_domain_role_assigned", args)


async def _write_execute(
    ledger: InMemoryLedger, tool: str, args: dict[str, Any],
) -> None:
    """Write one PEVR cycle whose execute step carries (tool, args)."""
    cid = _company_id()
    await ledger.write(
        company_id=cid,
        propose={
            "target_kind": tool.removeprefix("emit_"),
            "ref_id": str(uuid4()),
            "reason": f"seed {tool}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {"tool": tool, "args": args, "result_ref": str(uuid4())},
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


async def _call(mcp, name: str, **kwargs) -> Any:
    """Invoke a tool by name with a flat-token Context.

    Bypasses the HTTP transport. Uses the legacy flat ``API_TOKEN`` so
    the caller resolves to ``(person=None, role=admin)`` — i.e. the
    Phase 0 bearer-only path. Role-aware filter tests use the
    compact-token variant instead.
    """
    ctx = _ctx_with_token(API_TOKEN)
    return await _drive_tool_with_ctx(mcp, name, ctx, **kwargs)


@pytest.fixture
def mcp_server():
    ledger = InMemoryLedger()
    mcp = build_mcp_server(ledger=ledger, api_token=API_TOKEN)
    return mcp, ledger


# -------------------------------------------------------------------
# Sanity: every read tool registers under its canonical name.
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_all_read_tools_registered(mcp_server) -> None:
    mcp, _ = mcp_server
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    for tool_name in READ_TOOL_NAMES:
        assert tool_name in names, f"{tool_name} missing from tool registry"


# -------------------------------------------------------------------
# 11 happy-path tests, one per tool.
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_sources_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_source(ledger, kind="file")
    out = await _call(mcp, "query_sources", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert any(r.get("kind") == "file" for r in rows)


@pytest.mark.asyncio
async def test_query_kpis_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_kpi(ledger, name="Revenue")
    out = await _call(mcp, "query_kpis", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert any(r.get("name") == "Revenue" for r in rows)


@pytest.mark.asyncio
async def test_query_decisions_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_decision(ledger, text="push to friday")
    out = await _call(mcp, "query_decisions", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert any(r.get("decision_text") == "push to friday" for r in rows)


@pytest.mark.asyncio
async def test_query_processes_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_process(ledger, name="q3 close")
    out = await _call(mcp, "query_processes", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert any(r.get("process_name") == "q3 close" for r in rows)


@pytest.mark.asyncio
async def test_query_recurring_questions_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_recurring_question(ledger)
    out = await _call(mcp, "query_recurring_questions", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert rows[0]["normalized_question"] == "what is q3 revenue"


@pytest.mark.asyncio
async def test_query_system_map_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_system_node(ledger)
    out = await _call(mcp, "query_system_map", company_id=TENANT_SLUG)
    body = _extract_result(out)
    assert "nodes" in body and "edges" in body
    assert body["nodes"][0]["node_id"] == "carol"


@pytest.mark.asyncio
async def test_query_data_products_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_data_product(ledger)
    out = await _call(mcp, "query_data_products", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert rows[0]["kind"] == "chart"


@pytest.mark.asyncio
async def test_query_notebooks_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_notebook(ledger)
    out = await _call(mcp, "query_notebooks", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert rows[0]["name"] == "Q3 close"


@pytest.mark.asyncio
async def test_query_conversations_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_chat(ledger, classification="internal")
    out = await _call(mcp, "query_conversations", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert rows[0]["channel_id"] == "C-finance"


@pytest.mark.asyncio
async def test_query_persons_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_person(ledger, name="Carol")
    out = await _call(mcp, "query_persons", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    assert any(r.get("name") == "Carol" for r in rows)


@pytest.mark.asyncio
async def test_query_audit_trail_happy(mcp_server) -> None:
    mcp, ledger = mcp_server
    # Seed a few entries to produce execute trail rows.
    await _seed_kpi(ledger, name="Revenue")
    await _seed_decision(ledger)
    out = await _call(mcp, "query_audit_trail", company_id=TENANT_SLUG)
    rows = _extract_result(out)
    assert isinstance(rows, list)
    # Should include both seed entries plus the audit entries from prior tool calls.
    assert any(r.get("tool") == "emit_kpi_node" for r in rows)


# -------------------------------------------------------------------
# Audit pipeline assertion: every tool call writes exactly one
# mcp_call_received audit (PEVR cycle = 4 entries).
# -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tools_write_audit_entries(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed_kpi(ledger, name="Revenue")  # 4 entries
    before_rows = await ledger.fetch(_company_id())
    before = len(before_rows)
    await _call(mcp, "query_kpis", company_id=TENANT_SLUG)
    after_rows = await ledger.fetch(_company_id())
    # One PEVR cycle (4 entries) added by the audit.
    assert len(after_rows) - before == 4
    audit_execute = next(
        r for r in after_rows[before:] if r["kind"] == "execute"
    )
    assert audit_execute["payload"]["tool"] == "emit_mcp_call_received"
    assert audit_execute["payload"]["args"]["tool_name"] == "query_kpis"
    assert audit_execute["payload"]["args"]["outcome"] == "ok"


# -------------------------------------------------------------------
# Role-aware filter tests (sampling member / admin / observer).
#
# We use the compact-token path so the bearer carries a person_id; the
# test seeds role grants for that person and asserts the row counts
# match expectations.
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_aware_filter_member_sees_own_domain_only(mcp_server) -> None:
    mcp, ledger = mcp_server
    domain_a = uuid4()
    domain_b = uuid4()
    person = uuid4()
    # Member with grant on domain_a only.
    await _seed_role_grant(
        ledger, person_id=person, facet="tenancy", role="member",
    )
    await _seed_role_grant(
        ledger, person_id=person, facet="domain", role="contributor",
        domain_id=domain_a,
    )
    # Two KPIs: one on domain_a (visible), one on domain_b (hidden).
    await _seed_kpi(ledger, name="Revenue", domain=domain_a)
    await _seed_kpi(ledger, name="Pipeline", domain=domain_b)

    # Use the compact token path. We bypass the HTTP transport by using
    # an in-process tool call with a fabricated Context.
    rows = await _drive_tool_with_ctx(
        mcp, "query_kpis", _ctx_with_token(_token_for(person)),
        company_id=TENANT_SLUG,
    )
    names = {r["name"] for r in rows}
    assert "Revenue" in names
    assert "Pipeline" not in names


@pytest.mark.asyncio
async def test_role_aware_filter_admin_sees_all(mcp_server) -> None:
    mcp, ledger = mcp_server
    domain_a = uuid4()
    domain_b = uuid4()
    admin = uuid4()
    await _seed_role_grant(
        ledger, person_id=admin, facet="tenancy", role="admin",
    )
    await _seed_kpi(ledger, name="Revenue", domain=domain_a)
    await _seed_kpi(ledger, name="Pipeline", domain=domain_b)

    rows = await _drive_tool_with_ctx(
        mcp, "query_kpis", _ctx_with_token(_token_for(admin)),
        company_id=TENANT_SLUG,
    )
    names = {r["name"] for r in rows}
    assert {"Revenue", "Pipeline"} <= names


@pytest.mark.asyncio
async def test_role_aware_filter_observer_sees_all(mcp_server) -> None:
    mcp, ledger = mcp_server
    domain_a = uuid4()
    domain_b = uuid4()
    observer = uuid4()
    await _seed_role_grant(
        ledger, person_id=observer, facet="tenancy", role="observer",
    )
    await _seed_kpi(ledger, name="Revenue", domain=domain_a)
    await _seed_kpi(ledger, name="Pipeline", domain=domain_b)

    rows = await _drive_tool_with_ctx(
        mcp, "query_kpis", _ctx_with_token(_token_for(observer)),
        company_id=TENANT_SLUG,
    )
    names = {r["name"] for r in rows}
    assert {"Revenue", "Pipeline"} <= names


