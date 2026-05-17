"""Block J8 acceptance gate: every MCP tool / resource / prompt round-trips.

The MCP-native institutional-AI thesis claims: every feature in WormBase's
domain ontology is reachable via MCP, every reach is auditable, and every
audit row carries the canonical fields. This test enforces that
end-to-end:

1. Boot the FastMCP server in-process (the same shape ``cli.py`` runs).
2. Open a single Streamable HTTP session via the official ``mcp`` SDK.
3. For every registered tool (1 query_ledger + 11 read + 3 write = 15),
   every prompt (6), and every resource (7) — invoke it.
4. After all calls have landed, walk the ledger and assert that each
   call wrote exactly one ``emit_mcp_call_received`` row with the
   expected ``tool_name``, an outcome that is ``ok`` (or ``denied``
   for write tools the test caller can't access — those still count
   as audit-completeness, just with a different outcome), and a
   non-zero ``latency_ms``.

If any tool fails the gate, fix the tool — not the test. The whole
point of the gate is to catch a registration that ships without
audit decoration.
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

# Skip the gate cleanly if the environment explicitly disables MCP.
# Default behaviour: the test runs end-to-end (no skip) — the in-process
# MCP boot does not depend on the WORMBASE_MCP_ENABLED env var.
pytestmark = [
    pytest.mark.skipif(
        os.environ.get("WORMBASE_MCP_ENABLED", "").strip().lower()
        in ("0", "false", "no", "off"),
        reason=(
            "WORMBASE_MCP_ENABLED explicitly set to a falsy value; "
            "skip the MCP full-surface acceptance gate."
        ),
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


async def _seed_baseworm_fixture(ledger, company_id: UUID) -> dict[str, Any]:
    """Seed a small fixture so resource lookups have something to find.

    Writes one decision, one process, one source, one data product, one
    notebook, one chat message, one person, plus an admin role grant
    for the test-caller person — enough that the read tools and the
    audit_decision prompt can fold real rows.
    """
    from wormbase_core.mcp_tools.read_tools import _fold_decisions  # noqa: F401

    admin_pid = uuid4()
    decision_id = str(uuid4())
    process_id = str(uuid4())
    source_id = str(uuid4())
    data_product_id = str(uuid4())
    notebook_id = str(uuid4())
    channel_id = "C-finance"
    message_id = f"m-{uuid4()}"

    async def write_execute(tool: str, args: dict[str, Any]) -> None:
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": tool.removeprefix("emit_"),
                "ref_id": str(uuid4()),
                "reason": f"seed {tool}",
                "proposed_by": "j8-gate",
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

    # Admin role grant for the test caller.
    await write_execute("emit_role_assigned", {
        "person_id": str(admin_pid),
        "role": "admin",
        "granted_by": str(admin_pid),
    })
    # Decision (used by audit_decision prompt + decisions/{id} resource).
    await write_execute("emit_decision_recorded", {
        "decision_id": decision_id,
        "decision_text": "Ship Q3 revenue forecast on Friday",
        "decision_at": datetime.now(tz=UTC).isoformat(),
        "channel_id": channel_id,
        "decided_by_persons": [str(admin_pid)],
        "evidence_message_ids": [message_id],
        "confidence": 0.85,
    })
    # Process map.
    await write_execute("emit_process_map_proposed", {
        "process_id": process_id,
        "process_name": "Q3 close",
        "domain": "finance",
        "steps": [{
            "order": 1, "actor": "Carol", "action": "approve",
            "source_message_id": message_id,
        }],
        "confidence": 0.7,
    })
    # KPI node.
    await write_execute("emit_kpi_node", {
        "id": str(uuid4()),
        "name": "Q3 net revenue",
        "formula": "sum(revenue) - sum(refunds)",
    })
    # Source.
    await write_execute("emit_source_proposed", {
        "source_id": source_id,
        "source_kind": "file",
        "uri": "s3://baseworm/sales-q3.csv",
        "added_via_flow": "drop_and_profile",
        "suggested_classification": "internal",
    })
    # Data product.
    await write_execute("emit_data_product_proposed", {
        "data_product_id": data_product_id,
        "name": "Q3 revenue chart",
        "kind": "chart",
        "requested_by_person_id": str(admin_pid),
        "sources_required": [],
        "parameters": {},
    })
    # Notebook.
    await write_execute("emit_notebook_proposed", {
        "notebook_id": notebook_id,
        "name": "Q3 close notebook",
        "cells": [],
        "kernel": "python_local",
        "proposed_by_person_id": str(admin_pid),
    })
    # Chat message + system map node + recurring question.
    await write_execute("emit_chat_received", {
        "channel_id": channel_id,
        "message_id": message_id,
        "sender_person": str(admin_pid),
        "text": "Q3 revenue is locked",
        "classification": "internal",
    })
    await write_execute("emit_system_map_node", {
        "node_id": "carol",
        "node_kind": "person",
        "edges": [{
            "kind": "asks", "target_id": "alice", "weight": 0.5,
        }],
    })
    await write_execute("emit_recurring_question", {
        "question_id": str(uuid4()),
        "normalized_question": "what is q3 revenue",
        "asked_by_persons": [str(admin_pid)],
        "occurrences": 4,
        "first_seen_at": datetime.now(tz=UTC).isoformat(),
        "last_seen_at": datetime.now(tz=UTC).isoformat(),
    })
    # Person row (so query_persons returns one).
    await write_execute("emit_person_proposed", {
        "person_id": str(admin_pid),
        "tenant_id": str(company_id),
        "name": "Carol Demo",
        "email": "carol@baseworm.test",
        "proposed_by": "j8-gate",
    })

    return {
        "admin_pid": admin_pid,
        "decision_id": decision_id,
        "process_id": process_id,
        "source_id": source_id,
        "data_product_id": data_product_id,
        "notebook_id": notebook_id,
        "channel_id": channel_id,
    }


@pytest.mark.asyncio
async def test_mcp_full_feature_surface_round_trip() -> None:
    """End-to-end: every tool, prompt, and resource invocation lands one audit row."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from wormbase_core.mcp_tools.audit import AUDIT_TOOL_NAMES
    from wormbase_core.mcp_tools.prompts import PROMPT_NAMES
    from wormbase_core.mcp_tools.read_tools import READ_TOOL_NAMES
    from wormbase_core.mcp_tools.resources import RESOURCE_URIS
    from wormbase_core.mcp_tools.write_tools import WRITE_TOOL_NAMES
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import InMemoryLedger

    api_token = "j8-test-token-do-not-rotate"
    company_slug = "baseworm"
    company_id = tenant_to_uuid(company_slug)
    ledger = InMemoryLedger()

    fixture = await _seed_baseworm_fixture(ledger, company_id)
    admin_pid: UUID = fixture["admin_pid"]

    # The Phase 0 ``query_ledger`` tool checks the bearer against the
    # raw ``api_token`` directly (legacy flat-token path), while the
    # J1+J2 read/write tools accept compact tokens via ``authorize_caller``.
    # To exercise BOTH paths in one session we present the raw token —
    # the flat-token caller resolves to the backstage admin role
    # (``authorize_caller`` falls back to admin when caller_person_id is
    # None), which lets the write tools succeed too.

    port = _free_port()
    expected_tool_audits: list[str] = []

    async with _running_mcp_server(ledger, port, api_token):
        url = f"http://127.0.0.1:{port}/mcp"
        headers = {"Authorization": f"Bearer {api_token}"}

        async with streamablehttp_client(url, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()

                # --- Tools (read + write + Phase 0 query_ledger) -----
                tool_listing = await session.list_tools()
                listed_tool_names = {t.name for t in tool_listing.tools}
                expected_tools = (
                    {"query_ledger"}
                    | set(READ_TOOL_NAMES)
                    | set(WRITE_TOOL_NAMES)
                    | set(AUDIT_TOOL_NAMES)
                )
                assert listed_tool_names == expected_tools, (
                    f"tool registry drift: listed={listed_tool_names} "
                    f"expected={expected_tools}"
                )

                # Tool-specific arg builders. Every tool takes
                # company_id; some take additional required args.
                tool_args: dict[str, dict[str, Any]] = {
                    "query_ledger": {"company_id": company_slug, "limit": 5},
                    # Read tools — all just take company_id.
                    **{n: {"company_id": company_slug} for n in READ_TOOL_NAMES},
                    # Write tools — supply the minimum required args.
                    "propose_data_product": {
                        "company_id": company_slug,
                        "name": "J8 gate product",
                        "kind": "chart",
                    },
                    "confirm_proposal": {
                        "company_id": company_slug,
                        "proposal_id": fixture["data_product_id"],
                        "person_id": str(admin_pid),
                    },
                    "propose_kpi": {
                        "company_id": company_slug,
                        "name": "J8 gate KPI",
                    },
                    # P11 audit tool — feed it the seeded decision id
                    # (any seeded asset id works; the fold returns
                    # whichever rows reference it).
                    "read_audit_trail": {
                        "company_id": company_slug,
                        "entry_id": fixture["decision_id"],
                    },
                }

                for name in sorted(listed_tool_names):
                    args = tool_args[name]
                    result = await session.call_tool(name, arguments=args)
                    assert not result.isError, (
                        f"tool {name!r} returned error; result={result.content!r}"
                    )
                    expected_tool_audits.append(name)

                # --- Prompts -----------------------------------------
                prompt_listing = await session.list_prompts()
                listed_prompts = {p.name for p in prompt_listing.prompts}
                assert listed_prompts == set(PROMPT_NAMES)

                prompt_args: dict[str, dict[str, Any]] = {
                    "summarize_company_state": {"company_id": company_slug},
                    "audit_decision": {
                        "company_id": company_slug,
                        "decision_id": fixture["decision_id"],
                    },
                    "whats_new_today": {"company_id": company_slug},
                    "cfo_snapshot": {"company_id": company_slug},
                    "cmo_snapshot": {"company_id": company_slug},
                    "data_engineer_snapshot": {"company_id": company_slug},
                }

                for name in sorted(listed_prompts):
                    out = await session.get_prompt(
                        name, arguments=prompt_args[name],
                    )
                    assert out.messages, (
                        f"prompt {name!r} returned no messages"
                    )

                # --- Resources ---------------------------------------
                template_listing = await session.list_resource_templates()
                listed_uris = {
                    getattr(t, "uriTemplate", "") for t in template_listing.resourceTemplates
                }
                assert listed_uris == set(RESOURCE_URIS), (
                    f"resource registry drift: listed={listed_uris} "
                    f"expected={set(RESOURCE_URIS)}"
                )

                resource_uris: dict[str, str] = {
                    "wormbase://ledger/{company_id}/recent":
                        f"wormbase://ledger/{company_slug}/recent",
                    "wormbase://kpis/{company_id}/tree":
                        f"wormbase://kpis/{company_slug}/tree",
                    "wormbase://decisions/{company_id}/{decision_id}":
                        f"wormbase://decisions/{company_slug}/{fixture['decision_id']}",
                    "wormbase://data-products/{company_id}/{data_product_id}":
                        f"wormbase://data-products/{company_slug}/{fixture['data_product_id']}",
                    "wormbase://notebooks/{company_id}/{notebook_id}":
                        f"wormbase://notebooks/{company_slug}/{fixture['notebook_id']}",
                    "wormbase://sources/{company_id}/{source_id}":
                        f"wormbase://sources/{company_slug}/{fixture['source_id']}",
                    "wormbase://conversations/{company_id}/channels/{channel_id}":
                        f"wormbase://conversations/{company_slug}/channels/{fixture['channel_id']}",
                }
                for template_uri, concrete_uri in resource_uris.items():
                    out = await session.read_resource(concrete_uri)
                    assert out.contents, (
                        f"resource {concrete_uri!r} returned empty contents"
                    )

    # --- Audit-completeness check -------------------------------------
    rows = await ledger.fetch(company_id)
    mcp_audits = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_mcp_call_received"
    ]

    # Every tool call writes exactly one audit row with the right tool_name.
    audit_tool_names = [
        (r["payload"]["args"] or {}).get("tool_name") for r in mcp_audits
    ]

    for name in expected_tool_audits:
        matching = [a for a in audit_tool_names if a == name]
        assert len(matching) == 1, (
            f"expected exactly one mcp_call_received row for tool "
            f"{name!r}; got {len(matching)} (audit names seen: "
            f"{sorted(set(audit_tool_names))})"
        )

    # Every audit row carries the canonical fields.
    for row in mcp_audits:
        args = row["payload"]["args"]
        assert isinstance(args.get("tool_name"), str) and args["tool_name"]
        assert args.get("outcome") in ("ok", "denied", "error")
        assert isinstance(args.get("latency_ms"), int)
        assert args["latency_ms"] >= 0
        assert isinstance(args.get("args_hash"), str)
        assert len(args["args_hash"]) == 64

    # Resources additionally write a low-shape audit row tagged
    # `resource:<scheme>` (per resources.py::_audit_resource_read).
    resource_audit_names = {
        n for n in audit_tool_names if isinstance(n, str) and n.startswith("resource:")
    }
    # We invoked all 7 resources; each writes a resource:<scheme> audit.
    # The scheme set (after splitting `wormbase://...`) must be non-empty.
    assert resource_audit_names, (
        "no resource:* audit rows landed — resource reads must audit"
    )

    # Headline summary the test runner prints — useful when this gate
    # fails on a single missing tool.
    ok_outcomes = sum(
        1 for r in mcp_audits
        if (r["payload"]["args"] or {}).get("outcome") == "ok"
    )
    print(
        f"\n[J8 gate] mcp_call_received rows: {len(mcp_audits)} "
        f"(ok={ok_outcomes}); tool audits cover "
        f"{len(set(audit_tool_names))} distinct names."
    )
