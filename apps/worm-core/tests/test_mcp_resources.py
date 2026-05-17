"""Tests for the MCP resources catalog (J3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.mcp_tools.resources import RESOURCE_URIS
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-j3-resources"
TENANT_SLUG = "baseworm"


def _company_id() -> UUID:
    return tenant_to_uuid(TENANT_SLUG)


async def _seed(ledger: InMemoryLedger, tool: str, args: dict[str, Any]) -> None:
    cid = _company_id()
    await ledger.write(
        company_id=cid,
        propose={
            "target_kind": tool.removeprefix("emit_"), "ref_id": str(uuid4()),
            "reason": "seed", "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": tool, "args": args, "result_ref": str(uuid4()),
        },
        verify_fn=lambda _ep: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "seed"},
    )


@pytest.fixture
def mcp_server():
    ledger = InMemoryLedger()
    mcp = build_mcp_server(ledger=ledger, api_token=API_TOKEN)
    return mcp, ledger


async def _read_text(mcp, uri: str) -> str:
    contents = await mcp.read_resource(uri)
    parts = list(contents)
    assert parts, f"resource {uri} returned no contents"
    first = parts[0]
    return first.content if hasattr(first, "content") else str(first)


@pytest.mark.asyncio
async def test_resource_uris_registered(mcp_server) -> None:
    mcp, _ = mcp_server
    templates = await mcp.list_resource_templates()
    template_uris = {t.uriTemplate for t in templates}
    for uri in RESOURCE_URIS:
        assert uri in template_uris, f"{uri} not registered as template"


@pytest.mark.asyncio
async def test_ledger_recent(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed(ledger, "emit_kpi_node", {"id": "k1", "name": "Revenue"})
    text = await _read_text(mcp, f"wormbase://ledger/{TENANT_SLUG}/recent")
    body = json.loads(text)
    assert isinstance(body, list)
    assert any(r.get("kind") == "execute" for r in body)


@pytest.mark.asyncio
async def test_kpis_tree(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed(ledger, "emit_kpi_node", {"id": "k1", "name": "Revenue"})
    text = await _read_text(mcp, f"wormbase://kpis/{TENANT_SLUG}/tree")
    body = json.loads(text)
    assert any(n.get("name") == "Revenue" for n in body)


@pytest.mark.asyncio
async def test_decision_detail(mcp_server) -> None:
    mcp, ledger = mcp_server
    did = str(uuid4())
    now = datetime.now(tz=UTC)
    await _seed(ledger, "emit_decision_recorded", {
        "decision_id": did,
        "decision_text": "ship friday",
        "decision_at": now.isoformat(),
        "channel_id": "C-x",
        "decided_by_persons": [],
        "evidence_message_ids": ["m1"],
        "confidence": 0.9,
    })
    text = await _read_text(mcp, f"wormbase://decisions/{TENANT_SLUG}/{did}")
    body = json.loads(text)
    assert body["decision_text"] == "ship friday"


@pytest.mark.asyncio
async def test_data_product_detail(mcp_server) -> None:
    mcp, ledger = mcp_server
    dpid = str(uuid4())
    await _seed(ledger, "emit_data_product_proposed", {
        "data_product_id": dpid,
        "name": "Revenue Chart",
        "kind": "chart",
        "requested_by_person_id": str(uuid4()),
        "sources_required": [],
        "parameters": {},
    })
    text = await _read_text(
        mcp, f"wormbase://data-products/{TENANT_SLUG}/{dpid}",
    )
    body = json.loads(text)
    assert body["name"] == "Revenue Chart"


@pytest.mark.asyncio
async def test_notebook_detail_with_runs(mcp_server) -> None:
    mcp, ledger = mcp_server
    nbid = str(uuid4())
    rid = str(uuid4())
    await _seed(ledger, "emit_notebook_proposed", {
        "notebook_id": nbid,
        "name": "Q3 close",
        "cells": [],
        "kernel": "python",
        "proposed_by_person_id": str(uuid4()),
    })
    await _seed(ledger, "emit_notebook_run", {
        "notebook_id": nbid,
        "run_id": rid,
        "cell_outputs": [],
        "cell_hashes": [],
        "duration_ms": 100,
        "kernel_state_hash": "x",
        "status": "ok",
        "run_by": "test",
    })
    text = await _read_text(mcp, f"wormbase://notebooks/{TENANT_SLUG}/{nbid}")
    body = json.loads(text)
    assert body["name"] == "Q3 close"
    assert "runs" in body and body["runs"][0]["run_id"] == rid


@pytest.mark.asyncio
async def test_source_detail(mcp_server) -> None:
    mcp, ledger = mcp_server
    sid = str(uuid4())
    await _seed(ledger, "emit_source_proposed", {
        "source_id": sid,
        "source_kind": "file",
        "uri": "s3://demo/foo.csv",
        "added_via_flow": "drop_and_profile",
        "suggested_domain": "finance",
        "suggested_classification": "internal",
    })
    text = await _read_text(mcp, f"wormbase://sources/{TENANT_SLUG}/{sid}")
    body = json.loads(text)
    assert body["uri"] == "s3://demo/foo.csv"


@pytest.mark.asyncio
async def test_channel_recent_messages(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed(ledger, "emit_chat_received", {
        "channel_id": "C-finance",
        "message_id": "m1",
        "sender_person": str(uuid4()),
        "text": "hi",
        "classification": "internal",
    })
    text = await _read_text(
        mcp, f"wormbase://conversations/{TENANT_SLUG}/channels/C-finance",
    )
    body = json.loads(text)
    assert isinstance(body, list)
    assert body[0]["channel_id"] == "C-finance"
