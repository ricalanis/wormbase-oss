"""Tests for write_primitive: atomic 4-entry sequence, rollback on verify
failure, sequential per-company ordering, and the optional `timestamp`
parameter (sim clock controller passes explicit past timestamps)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.errors import VerifyFailed
from wormbase_ledger.hash_chain import verify_chain
from wormbase_ledger.repo import fetch_entries
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_write_primitive_appends_exactly_4_entries(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    async with session_scope(engine) as session:
        result = await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(uuid4()),
                "reason": "drop",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "profile_csv",
                "args": {"uri": "s3://x.csv"},
                "result_ref": "run-1",
            },
            verify_fn=lambda _res: {
                "checks": [{"name": "row_count", "passed": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )
    assert len(result.entry_ids) == 4
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    assert [r["kind"] for r in rows] == ["propose", "execute", "verify", "resolve"]
    assert all(r["quadrant"] in (
        "passive_deterministic",
        "passive_probabilistic",
        "active_deterministic",
        "active_probabilistic",
    ) for r in rows)
    ok, _ = verify_chain(rows)
    assert ok is True


@pytest.mark.asyncio
async def test_write_primitive_rolls_back_on_verify_failure(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    with pytest.raises(VerifyFailed):
        async with session_scope(engine) as session:
            await write_primitive(
                session,
                company_id=company_id,
                propose={
                    "target_kind": "source_proposed",
                    "ref_id": str(uuid4()),
                    "reason": "drop",
                    "proposed_by": "worm",
                },
                execute_fn=lambda: {"tool": "profile_csv", "args": {}, "result_ref": "r"},
                verify_fn=lambda _r: {
                    "checks": [{"name": "x", "passed": False}],
                    "passed": False,
                },
                resolve_fn=lambda _v: {"outcome": "discard", "rationale": "failed"},
            )
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    assert rows == []


@pytest.mark.asyncio
async def test_write_primitive_is_sequential_per_company(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    for _ in range(3):
        async with session_scope(engine) as session:
            await write_primitive(
                session,
                company_id=company_id,
                propose={
                    "target_kind": "memory_written",
                    "ref_id": str(uuid4()),
                    "reason": "r",
                    "proposed_by": "w",
                },
                execute_fn=lambda: {"tool": "noop", "args": {}, "result_ref": "r"},
                verify_fn=lambda _r: {"checks": [], "passed": True},
                resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            )
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    assert [r["seq"] for r in rows] == list(range(1, 13))


@pytest.mark.asyncio
async def test_write_primitive_accepts_explicit_timestamp(
    test_database_url: str,
) -> None:
    """Per Wave-2 review: sim clock controller (P5) passes explicit past
    timestamps via the `timestamp=` kwarg; default is now(UTC)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    backdate = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {"tool": "noop", "args": {}, "result_ref": "r"},
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            timestamp=backdate,
        )
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    assert all(abs((r["ts"] - backdate).total_seconds()) < 1 for r in rows)


@pytest.mark.asyncio
async def test_write_primitive_default_timestamp_is_now(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    before = datetime.now(UTC)
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {"tool": "noop", "args": {}, "result_ref": "r"},
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )
    after = datetime.now(UTC)
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    for r in rows:
        assert before - timedelta(seconds=1) <= r["ts"] <= after + timedelta(seconds=1)


@pytest.mark.asyncio
async def test_write_primitive_accepts_quadrant_override(
    test_database_url: str,
) -> None:
    """Per Wave-2 review: writer tags entries with quadrant at write time."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {"tool": "noop", "args": {}, "result_ref": "r"},
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    assert all(r["quadrant"] == "passive_probabilistic" for r in rows)
