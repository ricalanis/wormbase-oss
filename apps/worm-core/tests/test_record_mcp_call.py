"""Tests for write_actions.record_mcp_call (MCP Phase 0 spike).

Per docs/superpowers/specs/2026-04-27-mcp-integration.md §10.1.

Verifies that the orchestrator writes a full PEVR cycle (4 entries)
for one MCP call, that the execute body carries the canonical
mcp_call_received payload shape, and that outcome / args_hash /
caller_person_id / client_ua all flow through to the ledger entry.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from wormbase_core import write_actions
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_record_mcp_call_writes_pevr_cycle() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()

    args = {"company_id": str(company_id), "limit": 10}
    args_hash = hashlib.sha256(
        json.dumps(args, sort_keys=True).encode()
    ).hexdigest()
    started = datetime.now(tz=UTC)
    person_id = uuid4()

    cid, result = await write_actions.record_mcp_call(
        ledger,
        company_id,
        caller_person_id=person_id,
        tool_name="query_ledger",
        args_hash=args_hash,
        client_ua="claude-desktop/1.2.3",
        started_at=started,
        outcome="ok",
        latency_ms=42,
    )

    # Four entries: propose, execute, verify, resolve.
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    assert len(rows) == 4
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]

    execute_entry = rows[1]
    assert execute_entry["payload"]["tool"] == "emit_mcp_call_received"
    body = execute_entry["payload"]["args"]
    assert body["mcp_call_id"] == str(cid)
    assert body["tool_name"] == "query_ledger"
    assert body["args_hash"] == args_hash
    assert body["outcome"] == "ok"
    assert body["latency_ms"] == 42
    assert body["client_ua"] == "claude-desktop/1.2.3"
    assert body["caller_person_id"] == str(person_id)


@pytest.mark.asyncio
async def test_record_mcp_call_handles_anonymous_caller() -> None:
    """caller_person_id=None still writes the audit entry."""
    company_id = uuid4()
    ledger = InMemoryLedger()
    started = datetime.now(tz=UTC)

    cid, result = await write_actions.record_mcp_call(
        ledger,
        company_id,
        caller_person_id=None,
        tool_name="query_ledger",
        args_hash="0" * 64,
        client_ua=None,
        started_at=started,
        outcome="denied",
        latency_ms=3,
    )

    rows = await ledger.fetch(company_id)
    execute_entry = rows[1]
    body = execute_entry["payload"]["args"]
    assert body["caller_person_id"] is None
    assert body["client_ua"] is None
    assert body["outcome"] == "denied"
    assert execute_entry["payload"]["tool"] == "emit_mcp_call_received"


@pytest.mark.asyncio
async def test_record_mcp_call_outcomes() -> None:
    """All four canonical outcomes survive the round-trip."""
    company_id = uuid4()
    ledger = InMemoryLedger()
    for outcome in ("ok", "error", "denied", "timeout"):
        await write_actions.record_mcp_call(
            ledger,
            company_id,
            tool_name="query_ledger",
            args_hash="0" * 64,
            started_at=datetime.now(tz=UTC),
            outcome=outcome,
            latency_ms=1,
        )

    rows = await ledger.fetch(company_id)
    # 4 outcomes × 4-entry PEVR = 16 rows.
    assert len(rows) == 16
    execute_outcomes = [
        r["payload"]["args"]["outcome"]
        for r in rows
        if r["kind"] == "execute"
    ]
    assert sorted(execute_outcomes) == ["denied", "error", "ok", "timeout"]
