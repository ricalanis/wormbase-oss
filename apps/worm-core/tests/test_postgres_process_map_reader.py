"""Tests for ``LedgerProcessMapReader`` — v1.1 Task 6 (Hole #3 production wire-up).

Mirrors ``test_postgres_decision_reader.py`` for the process-map family.

The reader queries raw ledger entries matching ``payload->>'tool' ==
'emit_process_map_proposed'`` (mirrors the ``decision-chain.ts`` pattern
in the dashboard for /processes). Latest-status-per-process_id is
handled by collapsing to the most-recent execute entry per process_id —
the same DISTINCT-ON pattern the dashboard accessor uses for
``getProcessMaps``.

The implementation accepts any object exposing the ``Ledger.fetch``
surface — ``Ledger`` (Postgres-backed) or ``InMemoryLedger``.
These tests drive it with ``InMemoryLedger`` to keep the suite
deployment-free; the same code path runs against Postgres in
production because the ledger surface is identical.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_readers import LedgerProcessMapReader


pytestmark = pytest.mark.asyncio


COMPANY_ID = UUID("00000000-0000-0000-0000-0000000000aa")


async def _write_process_map(
    ledger: InMemoryLedger,
    *,
    process_id: UUID,
    process_name: str,
    domain: str = "general",
    domain_id: str | None = None,
    confidence: float = 0.85,
    steps: list[dict[str, Any]] | None = None,
) -> None:
    """Land one emit_process_map_proposed PEVR cycle."""
    args: dict[str, Any] = {
        "process_id": str(process_id),
        "process_name": process_name,
        "domain": domain,
        "confidence": confidence,
        "steps": steps if steps is not None else [
            {"order": 1, "actor": "Alice", "action": "draft",
             "source_message_id": "m-1"},
            {"order": 2, "actor": "Bob", "action": "review",
             "source_message_id": "m-2"},
        ],
    }
    if domain_id is not None:
        args["domain_id"] = domain_id
    await ledger.write(
        company_id=COMPANY_ID,
        propose={
            "target_kind": "process_map_proposed",
            "ref_id": str(process_id),
            "reason": "seed test process",
            "proposed_by": "test",
        },
        execute_fn=lambda a=args: {
            "tool": "emit_process_map_proposed",
            "args": a,
            "result_ref": str(process_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )


# ---------------------------------------------------------------------------
# list_process_maps
# ---------------------------------------------------------------------------


async def test_list_process_maps_returns_recent_first() -> None:
    """list_process_maps orders results latest-first by ledger insertion."""
    ledger = InMemoryLedger()
    p1 = uuid4()
    p2 = uuid4()
    p3 = uuid4()
    await _write_process_map(ledger, process_id=p1, process_name="Q1 close")
    # ensure ordering is non-degenerate even with same-second writes
    await asyncio.sleep(0)
    await _write_process_map(ledger, process_id=p2, process_name="Q2 close")
    await asyncio.sleep(0)
    await _write_process_map(ledger, process_id=p3, process_name="Q3 close")

    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=10,
    )

    assert len(rows) == 3
    # Most-recently-written first.
    assert rows[0]["process_id"] == str(p3)
    assert rows[-1]["process_id"] == str(p1)


async def test_list_process_maps_filters_by_domain_id() -> None:
    """domain_id filter returns only rows tagged with that domain."""
    ledger = InMemoryLedger()
    p_finance = uuid4()
    p_product = uuid4()
    await _write_process_map(
        ledger, process_id=p_finance, process_name="finance close",
        domain="finance", domain_id="d-finance",
    )
    await _write_process_map(
        ledger, process_id=p_product, process_name="release approval",
        domain="product", domain_id="d-product",
    )

    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id="d-finance", limit=10,
    )

    assert len(rows) == 1
    assert rows[0]["process_id"] == str(p_finance)
    assert rows[0]["domain_id"] == "d-finance"


async def test_list_process_maps_respects_limit() -> None:
    """limit caps the row count returned."""
    ledger = InMemoryLedger()
    for i in range(5):
        await _write_process_map(
            ledger, process_id=uuid4(), process_name=f"process {i}",
        )

    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=2,
    )

    assert len(rows) == 2


async def test_list_process_maps_returns_empty_when_no_processes() -> None:
    """Empty ledger yields empty list (not None)."""
    ledger = InMemoryLedger()
    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=50,
    )
    assert rows == []


async def test_list_process_maps_collapses_to_latest_per_process_id() -> None:
    """Multiple emit_process_map_proposed for same process_id -> one row,
    carrying the latest payload.

    The dashboard's ``getProcessMaps`` DISTINCT-ON pattern guarantees
    one row per ``process_id`` from the most recent ledger entry; the
    MCP reader matches that semantics so admin reprocesses don't yield
    duplicate listings.
    """
    ledger = InMemoryLedger()
    pid = uuid4()
    await _write_process_map(
        ledger, process_id=pid, process_name="initial name", confidence=0.5,
    )
    await asyncio.sleep(0)
    await _write_process_map(
        ledger, process_id=pid, process_name="refined name", confidence=0.95,
    )

    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=10,
    )
    assert len(rows) == 1
    # The latest payload won.
    assert rows[0]["process_name"] == "refined name"
    assert rows[0]["confidence"] == pytest.approx(0.95)


async def test_list_process_maps_only_counts_execute_entries() -> None:
    """propose/verify/resolve siblings in the PEVR cycle are ignored —
    we only walk execute entries that carry ``tool == 'emit_process_map_proposed'``.
    """
    ledger = InMemoryLedger()
    await _write_process_map(
        ledger, process_id=uuid4(), process_name="single map",
    )
    # Each PEVR cycle lands 4 entries — but only the execute row is a
    # process-map. The reader should never double-count.
    reader = LedgerProcessMapReader(ledger=ledger)
    rows = await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=10,
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# get_process_map
# ---------------------------------------------------------------------------


async def test_get_process_map_returns_one_when_found() -> None:
    """get_process_map returns the row whose process_id matches."""
    ledger = InMemoryLedger()
    target = uuid4()
    decoy = uuid4()
    await _write_process_map(
        ledger, process_id=target, process_name="target process",
    )
    await _write_process_map(
        ledger, process_id=decoy, process_name="decoy process",
    )

    reader = LedgerProcessMapReader(ledger=ledger)
    row = await reader.get_process_map(
        company_id=COMPANY_ID, process_map_id=str(target),
    )
    assert row is not None
    assert row["process_id"] == str(target)
    assert row["process_name"] == "target process"


async def test_get_process_map_returns_none_when_missing() -> None:
    """get_process_map returns None for an unknown id."""
    ledger = InMemoryLedger()
    await _write_process_map(
        ledger, process_id=uuid4(), process_name="some process",
    )
    reader = LedgerProcessMapReader(ledger=ledger)
    row = await reader.get_process_map(
        company_id=COMPANY_ID,
        process_map_id="00000000-0000-0000-0000-deadbeef0000",
    )
    assert row is None


async def test_get_process_map_returns_latest_payload() -> None:
    """get_process_map collapses to the latest execute entry per process_id."""
    ledger = InMemoryLedger()
    pid = uuid4()
    await _write_process_map(
        ledger, process_id=pid, process_name="v1", confidence=0.5,
    )
    await asyncio.sleep(0)
    await _write_process_map(
        ledger, process_id=pid, process_name="v2", confidence=0.9,
    )

    reader = LedgerProcessMapReader(ledger=ledger)
    row = await reader.get_process_map(
        company_id=COMPANY_ID, process_map_id=str(pid),
    )
    assert row is not None
    assert row["process_name"] == "v2"


async def test_get_process_map_returns_none_on_empty_ledger() -> None:
    """Empty ledger returns None — no scan errors."""
    ledger = InMemoryLedger()
    reader = LedgerProcessMapReader(ledger=ledger)
    row = await reader.get_process_map(
        company_id=COMPANY_ID,
        process_map_id="00000000-0000-0000-0000-000000000000",
    )
    assert row is None


# ---------------------------------------------------------------------------
# Protocol conformance (sanity check)
# ---------------------------------------------------------------------------


async def test_reader_satisfies_process_map_reader_protocol() -> None:
    """LedgerProcessMapReader is a structural match for the Protocol."""
    from wormbase_agent_gateway.mcp_server.tools_decisions import ProcessMapReader

    ledger = InMemoryLedger()
    reader: ProcessMapReader = LedgerProcessMapReader(ledger=ledger)
    # If the Protocol does not match, mypy / runtime checks would
    # complain. The annotation is the actual check; the call below
    # just exercises both methods.
    assert await reader.list_process_maps(
        company_id=COMPANY_ID, domain_id=None, limit=1,
    ) == []
    assert await reader.get_process_map(
        company_id=COMPANY_ID, process_map_id=str(uuid4()),
    ) is None
