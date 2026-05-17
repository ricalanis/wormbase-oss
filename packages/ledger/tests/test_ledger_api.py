"""Tests for the public Ledger / InMemoryLedger surface used by P3, 2C, P4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wormbase_ledger import InMemoryLedger, Ledger


def _propose_args(memory_id):
    return dict(
        propose={
            "target_kind": "memory_written",
            "ref_id": str(memory_id),
            "reason": "r",
            "proposed_by": "w",
        },
        execute_fn=lambda: {
            "tool": "emit_memory_written",
            "args": {"memory_id": str(memory_id), "content": "c", "tags": []},
            "result_ref": "r",
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


@pytest.mark.asyncio
async def test_ledger_class_writes_and_verifies(test_database_url: str) -> None:
    ledger = Ledger(test_database_url)
    company_id = uuid4()
    res = await ledger.write(company_id=company_id, **_propose_args(uuid4()))
    assert len(res.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]

    report = await ledger.verify(company_id)
    assert report.ok is True

    snap = await ledger.replay(company_id, datetime.now(UTC) + timedelta(hours=1))
    assert len(snap.projections.memory) == 1


@pytest.mark.asyncio
async def test_in_memory_ledger_matches_disk_semantics() -> None:
    mem = InMemoryLedger()
    company_id = uuid4()
    memory_id = uuid4()
    res = await mem.write(company_id=company_id, **_propose_args(memory_id))
    assert len(res.entry_ids) == 4

    rows = await mem.fetch(company_id)
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]
    # All four entries share the same memory_id because of the propose/exec
    # threading; we just assert chain integrity here.

    report = await mem.verify(company_id)
    assert report.ok is True
    assert report.entries_checked == 4

    snap = await mem.replay(company_id, datetime.now(UTC) + timedelta(hours=1))
    assert len(snap.projections.memory) == 1
    assert len(snap.hash_of_projections) == 32


@pytest.mark.asyncio
async def test_ledger_get_entry_direct_lookup(test_database_url: str) -> None:
    """DB-backed ``Ledger.get_entry`` returns one normalized entry or None.

    v1.2 follow-up #4 — direct primary-key lookup replaces iteration
    over ``fetch`` for entry-id resolution (e.g. promote_semantic_gap).
    """
    ledger = Ledger(test_database_url)
    company_id = uuid4()
    res = await ledger.write(company_id=company_id, **_propose_args(uuid4()))

    # All 4 entry ids round-trip individually.
    for entry_id in res.entry_ids:
        entry = await ledger.get_entry(company_id, entry_id)
        assert entry is not None
        assert entry["entry_id"] == entry_id
        assert entry["company_id"] == company_id

    # Missing id → None (no exception).
    assert await ledger.get_entry(company_id, uuid4()) is None

    # Wrong tenant → None even when the entry id exists elsewhere.
    other_company = uuid4()
    assert await ledger.get_entry(other_company, res.entry_ids[0]) is None


@pytest.mark.asyncio
async def test_in_memory_ledger_get_entry_direct_lookup() -> None:
    """InMemoryLedger surface mirrors the DB-backed ``get_entry`` shape."""
    mem = InMemoryLedger()
    company_id = uuid4()
    res = await mem.write(company_id=company_id, **_propose_args(uuid4()))

    for entry_id in res.entry_ids:
        entry = await mem.get_entry(company_id, entry_id)
        assert entry is not None
        assert entry["entry_id"] == entry_id

    assert await mem.get_entry(company_id, uuid4()) is None
    assert await mem.get_entry(uuid4(), res.entry_ids[0]) is None


@pytest.mark.asyncio
async def test_in_memory_ledger_rolls_back_on_verify_fail() -> None:
    mem = InMemoryLedger()
    company_id = uuid4()
    from wormbase_ledger.errors import VerifyFailed

    with pytest.raises(VerifyFailed):
        await mem.write(
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {"tool": "noop", "args": {}, "result_ref": "r"},
            verify_fn=lambda _r: {"checks": [], "passed": False},
            resolve_fn=lambda _v: {"outcome": "discard", "rationale": "no"},
        )
    rows = await mem.fetch(company_id)
    assert rows == []
