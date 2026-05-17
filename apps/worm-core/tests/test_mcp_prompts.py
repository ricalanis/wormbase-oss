"""Tests for the MCP prompts catalog (J3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_core.mcp_server import build_mcp_server
from wormbase_core.mcp_tools.prompts import PROMPT_NAMES
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger

API_TOKEN = "test-token-j3-prompts"
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


def _msg_text(messages: list[Any]) -> str:
    """Concatenate the text content of returned messages."""
    parts = []
    for m in messages:
        c = getattr(m, "content", None)
        if c is None and isinstance(m, dict):
            c = m.get("content")
        if hasattr(c, "text"):
            parts.append(c.text)
        elif isinstance(c, dict) and "text" in c:
            parts.append(c["text"])
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_all_prompts_registered(mcp_server) -> None:
    mcp, _ = mcp_server
    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    for prompt_name in PROMPT_NAMES:
        assert prompt_name in names


@pytest.mark.asyncio
async def test_summarize_company_state(mcp_server) -> None:
    mcp, ledger = mcp_server
    await _seed(ledger, "emit_kpi_node", {"id": "k1", "name": "Revenue"})
    result = await mcp.get_prompt(
        "summarize_company_state", {"company_id": TENANT_SLUG},
    )
    text = _msg_text(result.messages)
    assert "Revenue" in text or "KPI" in text


@pytest.mark.asyncio
async def test_audit_decision_with_match(mcp_server) -> None:
    mcp, ledger = mcp_server
    did = str(uuid4())
    now = datetime.now(tz=UTC)
    await _seed(ledger, "emit_decision_recorded", {
        "decision_id": did,
        "decision_text": "push to friday",
        "decision_at": now.isoformat(),
        "channel_id": "C-finance",
        "decided_by_persons": [],
        "evidence_message_ids": ["m1"],
        "confidence": 0.8,
    })
    result = await mcp.get_prompt(
        "audit_decision", {"company_id": TENANT_SLUG, "decision_id": did},
    )
    text = _msg_text(result.messages)
    assert "push to friday" in text


@pytest.mark.asyncio
async def test_audit_decision_not_found(mcp_server) -> None:
    mcp, _ = mcp_server
    bogus = str(uuid4())
    result = await mcp.get_prompt(
        "audit_decision", {"company_id": TENANT_SLUG, "decision_id": bogus},
    )
    text = _msg_text(result.messages)
    assert "No decision found" in text


@pytest.mark.asyncio
async def test_whats_new_today(mcp_server) -> None:
    mcp, _ = mcp_server
    result = await mcp.get_prompt(
        "whats_new_today", {"company_id": TENANT_SLUG},
    )
    text = _msg_text(result.messages)
    assert "Daily digest" in text or "digest" in text


@pytest.mark.asyncio
async def test_cfo_snapshot(mcp_server) -> None:
    mcp, _ = mcp_server
    result = await mcp.get_prompt(
        "cfo_snapshot", {"company_id": TENANT_SLUG},
    )
    text = _msg_text(result.messages)
    assert "CFO" in text


@pytest.mark.asyncio
async def test_data_engineer_snapshot(mcp_server) -> None:
    mcp, _ = mcp_server
    result = await mcp.get_prompt(
        "data_engineer_snapshot", {"company_id": TENANT_SLUG},
    )
    text = _msg_text(result.messages)
    assert "Data Engineer" in text or "data engineer" in text.lower()
