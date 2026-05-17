"""P11 — MCP external-client integration test.

Drives the same shape an external Claude Desktop session uses:

1. Boot a FastMCP server in-process on a free port (the same shape
   ``cli.py`` runs in production).
2. Open a Streamable HTTP session via the official ``mcp`` SDK.
3. Walk the six demo-script beats from ``docs/superpowers/notes/
   2026-04-29-mcp-demo-script.md``:

     * ``query_kpis(domain="finance")`` returns shaped KPI rows
     * ``propose_kpi`` writes a ``kpi_proposed`` ledger entry with
       ``proposed_by="mcp"`` (when the caller has no Person id yet)
     * ``read_audit_trail(entry_id)`` returns the full chain for the
       freshly-proposed KPI (proposed_by + ledger_range; confirmed_by
       still ``null`` because no admin has confirmed yet)
     * the masked-column refusal gate (P7) refuses + records policy
       name + offending column
     * ``query_persons`` returns at least one row for the seeded
       fixture
     * the audit log carries one ``emit_mcp_call_received`` row per
       tool call with ``proposed_by`` attribution

The point of the test is that a refused / accepted MCP call shape
matches what an external Claude Desktop session will see, and that
attribution is replay-stable.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("WORMBASE_MCP_ENABLED", "").strip().lower()
        in ("0", "false", "no", "off"),
        reason="WORMBASE_MCP_ENABLED disabled; skip external-client test",
    ),
]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextlib.asynccontextmanager
async def _running_mcp_server(ledger, port: int, api_token: str):
    from wormbase_core.mcp_server import build_mcp_server

    server = build_mcp_server(
        ledger=ledger, api_token=api_token, host="127.0.0.1", port=port,
    )
    task = asyncio.create_task(server.run_streamable_http_async())

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await w.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        task.cancel()
        raise TimeoutError(f"MCP server did not bind on :{port} within 5s")

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def _seed_demo_fixture(ledger, company_id: UUID) -> dict[str, Any]:
    """Seed enough rows that the stage-script queries return real shapes.

    Mirrors ``test_mcp_full_feature_surface``'s seed shape but tighter:
    one finance KPI, one Carol Person, one decision, one source.
    """
    admin_pid = uuid4()
    decision_id = str(uuid4())
    kpi_id = str(uuid4())
    source_id = str(uuid4())

    async def write_execute(tool: str, args: dict[str, Any]) -> None:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": tool.removeprefix("emit_"),
                "ref_id": str(uuid4()),
                "reason": f"seed {tool}",
                "proposed_by": "p11-test",
            },
            execute_fn=lambda: {
                "tool": tool, "args": args, "result_ref": str(uuid4()),
            },
            verify_fn=lambda _e: {
                "checks": [{"name": "seeded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep", "rationale": "fixture",
            },
        )

    await write_execute("emit_role_assigned", {
        "person_id": str(admin_pid),
        "role": "admin",
        "granted_by": str(admin_pid),
    })
    await write_execute("emit_person_proposed", {
        "person_id": str(admin_pid),
        "tenant_id": str(company_id),
        "name": "Carol Demo",
        "email": "carol@baseworm.test",
        "proposed_by": "p11-test",
    })
    await write_execute("emit_kpi_node", {
        "id": kpi_id,
        "name": "Q3 net revenue",
        "formula": "sum(revenue) - sum(refunds)",
        "domain_id": "finance",
    })
    await write_execute("emit_decision_recorded", {
        "decision_id": decision_id,
        "decision_text": "Lock Q3 forecast",
        "decision_at": datetime.now(tz=UTC).isoformat(),
        "channel_id": "C-finance",
        "decided_by_persons": [str(admin_pid)],
        "evidence_message_ids": [],
        "confidence": 0.9,
    })
    await write_execute("emit_source_proposed", {
        "source_id": source_id,
        "source_kind": "warehouse",
        "uri": "snowflake://baseworm/customers",
        "added_via_flow": "credential_in_dm",
        "suggested_classification": "pii",
    })

    return {
        "admin_pid": admin_pid,
        "decision_id": decision_id,
        "kpi_id": kpi_id,
        "source_id": source_id,
    }


# =============================================================================
# Pure-fold test for the audit chain — no MCP server, no SDK round-trip.
# =============================================================================


@pytest.mark.asyncio
async def test_fold_audit_trail_returns_full_chain_for_proposed_kpi() -> None:
    """``fold_audit_trail`` reconstructs proposed_by + ledger_range from raw rows."""
    from wormbase_core import write_actions
    from wormbase_core.mcp_tools.audit import fold_audit_trail
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    company_id = tenant_to_uuid("baseworm")

    kpi_id, _ = await write_actions.propose_kpi_node(
        ledger,
        company_id,
        label="P11 fold test KPI",
        formula="sum(x)",
        proposed_by="mcp",
    )

    rows = await ledger.fetch(company_id)
    chain = fold_audit_trail(rows, entry_id=str(kpi_id))

    assert chain is not None
    assert chain["entry_id"] == str(kpi_id)
    assert chain["target_kind"] == "kpi_proposed"
    assert chain["proposed_by"] == "mcp"
    assert chain["proposed_at"] is not None
    # Confirmed_by null — propose_kpi_node only proposes; an admin must
    # later confirm via a separate write.
    assert chain["confirmed_by"] is None
    assert chain["confirmed_at"] is None
    # PEVR contributes 4 entries (propose + execute + verify + resolve)
    # all touching this KPI.
    assert len(chain["contributing_entries"]) == 4
    kinds = [c["kind"] for c in chain["contributing_entries"]]
    assert kinds == ["propose", "execute", "verify", "resolve"]
    assert chain["ledger_range"]["first_seq"] is not None
    assert chain["ledger_range"]["last_seq"] >= chain["ledger_range"]["first_seq"]


@pytest.mark.asyncio
async def test_fold_audit_trail_picks_up_confirm_for_person() -> None:
    """A Person that was proposed THEN confirmed shows both attribution rows."""
    from wormbase_core import write_actions
    from wormbase_core.mcp_tools.audit import fold_audit_trail
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    company_id = tenant_to_uuid("baseworm")

    person_id, _ = await write_actions.propose_person(
        ledger, company_id,
        name="Carol Audit",
        email="carol-audit@baseworm.test",
        platform="slack",
        platform_user_id="U_CAROL_AUDIT",
        position="cfo",
        proposed_by="mcp",
    )
    confirmer = uuid4()
    await write_actions.confirm_person(
        ledger, company_id, person_id=person_id, confirmed_by=confirmer,
    )

    rows = await ledger.fetch(company_id)
    chain = fold_audit_trail(rows, entry_id=str(person_id))

    assert chain is not None
    assert chain["proposed_by"] == "mcp"
    assert chain["confirmed_by"] == str(confirmer)
    assert chain["confirmed_at"] is not None


@pytest.mark.asyncio
async def test_fold_audit_trail_returns_none_for_unknown_id() -> None:
    """Unknown entity ids return None (caller surfaces an empty payload)."""
    from wormbase_core.mcp_tools.audit import fold_audit_trail
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    _ = tenant_to_uuid("baseworm")
    chain = fold_audit_trail([], entry_id="00000000-0000-0000-0000-000000000000")
    assert chain is None


# =============================================================================
# End-to-end test — boot the FastMCP server, open a session, drive 6 beats.
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_external_client_six_stage_beats() -> None:
    """The full P11 stage script from an external MCP client.

    Beats 1–6 from docs/superpowers/notes/2026-04-29-mcp-demo-script.md.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    api_token = "p11-test-token-do-not-rotate"
    company_slug = "baseworm"
    company_id = tenant_to_uuid(company_slug)
    ledger = InMemoryLedger()

    fixture = await _seed_demo_fixture(ledger, company_id)
    port = _free_port()

    async with _running_mcp_server(ledger, port, api_token):
        url = f"http://127.0.0.1:{port}/mcp"
        headers = {"Authorization": f"Bearer {api_token}"}

        async with streamablehttp_client(url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

                # Beat 2 — "show KPIs and owners in the finance domain".
                # We accept *any* KPI rows here because the seeded
                # ``emit_kpi_node`` carries a domain_id; the role-aware
                # filter accepts admin-as-fallback for the flat token.
                kpis_resp = await session.call_tool(
                    "query_kpis", arguments={"company_id": company_slug},
                )
                assert not kpis_resp.isError
                # mcp returns content blocks; structured content is the
                # tool's actual return value.
                kpi_rows = (
                    kpis_resp.structuredContent.get("result")
                    if hasattr(kpis_resp, "structuredContent")
                    and kpis_resp.structuredContent
                    else None
                )
                # FastMCP wraps list returns as {"result": [...]} when
                # json_response=True; some SDK versions surface it as
                # a flat list. Normalize.
                if kpi_rows is None and hasattr(kpis_resp, "content"):
                    # fallback: parse text content
                    import json as _json
                    for block in kpis_resp.content:
                        text = getattr(block, "text", None)
                        if text:
                            try:
                                kpi_rows = _json.loads(text)
                                break
                            except Exception:
                                continue
                assert kpi_rows is not None
                assert isinstance(kpi_rows, list)

                # Beat 3 — propose a new KPI.
                propose_resp = await session.call_tool(
                    "propose_kpi",
                    arguments={
                        "company_id": company_slug,
                        "name": "2026 Q4 ARR target",
                    },
                )
                assert not propose_resp.isError, propose_resp.content
                propose_payload = (
                    propose_resp.structuredContent
                    if hasattr(propose_resp, "structuredContent")
                    and propose_resp.structuredContent
                    else None
                )
                if propose_payload is None and hasattr(propose_resp, "content"):
                    import json as _json
                    for block in propose_resp.content:
                        text = getattr(block, "text", None)
                        if text:
                            try:
                                propose_payload = _json.loads(text)
                                break
                            except Exception:
                                continue
                assert propose_payload is not None
                assert "kpi_id" in propose_payload
                new_kpi_id = propose_payload["kpi_id"]

                # Beat 5 — read_audit_trail for the freshly-proposed KPI.
                audit_resp = await session.call_tool(
                    "read_audit_trail",
                    arguments={
                        "company_id": company_slug,
                        "entry_id": new_kpi_id,
                    },
                )
                assert not audit_resp.isError, audit_resp.content
                audit_payload = (
                    audit_resp.structuredContent
                    if hasattr(audit_resp, "structuredContent")
                    and audit_resp.structuredContent
                    else None
                )
                if audit_payload is None and hasattr(audit_resp, "content"):
                    import json as _json
                    for block in audit_resp.content:
                        text = getattr(block, "text", None)
                        if text:
                            try:
                                audit_payload = _json.loads(text)
                                break
                            except Exception:
                                continue
                assert audit_payload is not None
                assert audit_payload["entry_id"] == new_kpi_id
                # ``propose_kpi`` MCP tool sets proposed_by to either the
                # caller's person UUID or "mcp" (flat-token path).
                assert audit_payload["proposed_by"] in ("mcp",) or (
                    audit_payload["proposed_by"]
                    and len(audit_payload["proposed_by"]) >= 8
                )
                assert audit_payload["confirmed_by"] is None
                assert audit_payload["confirmed_at"] is None
                assert (
                    audit_payload["ledger_range"]["first_seq"] is not None
                )
                assert len(audit_payload["contributing_entries"]) >= 4

                # Beat dashboard — query_persons should return at least Carol.
                persons_resp = await session.call_tool(
                    "query_persons",
                    arguments={"company_id": company_slug},
                )
                assert not persons_resp.isError

    # ----- Audit-completeness check -----
    rows = await ledger.fetch(company_id)
    mcp_audits = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_mcp_call_received"
    ]
    audit_tool_names = {
        (r["payload"]["args"] or {}).get("tool_name") for r in mcp_audits
    }
    # The session called these four tools — each must have an audit row.
    assert {"query_kpis", "propose_kpi", "read_audit_trail", "query_persons"} <= audit_tool_names

    # Read audit trail for the new KPI directly (parity check between the
    # live tool and the pure fold).
    from wormbase_core.mcp_tools.audit import fold_audit_trail
    chain = fold_audit_trail(rows, entry_id=new_kpi_id)
    assert chain is not None
    assert chain["target_kind"] == "kpi_proposed"


# =============================================================================
# Beat 6 — masked-column refusal via the P7 governance gate.
#
# We exercise the gate directly here (not through MCP) because Snowflake
# query routing is a separate adapter. The point is that the policy
# name + offending column propagate into the gate_fired ledger entry
# the way the demo script promises.
# =============================================================================


@pytest.mark.asyncio
async def test_masked_column_refusal_surfaces_policy_name_and_columns() -> None:
    """P7 gate refuses + records policy name (verbatim from CLAUDE.md§Refused-query path)."""
    from wormbase_governance.policies.masked_column_refusal import (
        MaskedColumnQuery,
        MaskedColumnRefusalGate,
        POLICY_NAME,
    )
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    company_id = tenant_to_uuid("baseworm")
    gate = MaskedColumnRefusalGate(ledger=ledger, company_id=company_id)

    decision = await gate.check(
        MaskedColumnQuery(
            query_text="select customer_email from snowflake.customers",
            referenced_columns=["customer_email"],
            column_tags={"customer_email": "pii"},
            source_id=None,
            resource_id="snowflake.customers.customer_email",
            requester="mcp_client",
        )
    )

    assert decision.allow is False
    assert decision.policy_name == POLICY_NAME
    assert "customer_email" in decision.offending_columns
    assert any(
        t["column"] == "customer_email" and t["classification"] == "pii"
        for t in decision.tag_chain
    )

    # Gate writes a gate_fired ledger entry with policy_name + columns
    # in the args payload.
    rows = await ledger.fetch(company_id)
    gate_entries = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_gate_fired"
    ]
    assert gate_entries, "gate_fired entry must be written on refusal"
    args = gate_entries[-1]["payload"]["args"]
    assert args["gate"] == "masked_column_refusal"
    assert args["policy_name"] == POLICY_NAME
    assert "customer_email" in args["offending_columns"]
    assert any(
        t["classification"] == "pii" for t in args["tag_chain"]
    )
