"""Tests for the engine-per-tenant parallel-replay validator.

Engine-per-tenant Phase 2 — companion to ``tenant_engine_registered``.
Pins the validator contract that compares a tenant's ledger entries
across two engines (shared vs isolated) over a closed time window, so
an operator can certify hash-chain equivalence before a Shape A →
Shape B migration cutover.

Phase 1+2 ships the validator + contract; Phase 3 will wire it into
the admin migration tool's go/no-go gate.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wormbase_core.tenant_engine_validator import (
    ParallelReplayDiff,
    validate_parallel_replay,
)
from wormbase_ledger import Ledger
from wormbase_ledger.db import session_scope
from wormbase_ledger.repo import fetch_entries, insert_entry
from wormbase_ledger.schema import metadata


async def _make_engine() -> AsyncEngine:
    """Construct an in-memory aiosqlite engine with the ledger schema."""
    # File-based per-fixture URL because :memory: SQLite is per-connection
    # — two engines wouldn't share state, but we want fresh DBs anyway.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:{uuid4().hex}?mode=memory&cache=shared&uri=true",
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    return engine


async def _copy_entries(
    src_engine: AsyncEngine,
    dst_engine: AsyncEngine,
    company_id: UUID,
) -> None:
    """Copy ledger entries byte-for-byte from src to dst.

    Mirrors the Phase 3 admin migration semantic: the isolated engine
    is seeded by copying the shared engine's rows (same entry_id,
    same hashes, same payload) so a parallel-replay validator can
    certify byte-exact equivalence before cutover.
    """
    async with session_scope(src_engine) as session:
        rows = await fetch_entries(session, company_id)
    async with session_scope(dst_engine) as session:
        for row in rows:
            await insert_entry(session, dict(row))


def _propose_args(memory_id: UUID) -> dict[str, Any]:
    """Boilerplate for a propose → execute → verify → resolve cycle.

    ``propose`` is a payload dict; ``execute_fn`` takes no arguments
    and returns the execute body; ``verify_fn`` / ``resolve_fn`` take
    one dict (the prior payload) and return their own bodies. See
    ``packages/ledger/src/wormbase_ledger/write_primitive.py``.
    """
    return dict(
        propose={
            "target_kind": "memory_written",
            "target_id": str(memory_id),
            "rationale": "test cycle",
        },
        execute_fn=lambda: {
            "memory_id": str(memory_id),
            "text": "hello world",
            "tags": [],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


@pytest.mark.asyncio
async def test_parallel_replay_identical_engines_consistent() -> None:
    """Two engines holding the SAME entries return is_consistent=True.

    Mirrors the Phase 3 admin migration: the isolated engine is
    seeded by copying the shared engine's rows byte-for-byte (same
    entry_id, same hashes), so parallel-replay certifies byte-exact
    equivalence before cutover.
    """
    shared_engine = await _make_engine()
    isolated_engine = await _make_engine()
    try:
        company_id = uuid4()
        memory_id = uuid4()

        shared_ledger = Ledger(shared_engine)
        await shared_ledger.write(
            company_id=company_id, **_propose_args(memory_id),
        )
        # Copy rows from shared to isolated to mirror migration seed.
        await _copy_entries(shared_engine, isolated_engine, company_id)

        window_start = datetime.now(UTC) - timedelta(hours=1)
        window_end = datetime.now(UTC) + timedelta(hours=1)
        diff = await validate_parallel_replay(
            tenant_slug="acme",
            shared_engine=shared_engine,
            isolated_engine=isolated_engine,
            company_id=company_id,
            window_start=window_start,
            window_end=window_end,
        )

        assert isinstance(diff, ParallelReplayDiff)
        assert diff.tenant_slug == "acme"
        assert diff.shared_entry_count == 4
        assert diff.isolated_entry_count == 4
        assert diff.is_consistent is True
        assert diff.inconsistency_reasons == ()
        # Per-kind counts: 1 each for propose, execute, verify, resolve
        # (memory_written is the *target* kind, not the entry kind on the
        # write_primitive output — entry kinds are the four canonical
        # phases plus the memory_written write itself).
        # We don't pin exact counts here; just that they match.
        assert diff.kind_counts_shared == diff.kind_counts_isolated
    finally:
        await shared_engine.dispose()
        await isolated_engine.dispose()


@pytest.mark.asyncio
async def test_parallel_replay_diverging_engines_inconsistent() -> None:
    """When engines diverge (one has more entries), is_consistent=False."""
    shared_engine = await _make_engine()
    isolated_engine = await _make_engine()
    try:
        company_id = uuid4()
        memory_id_1 = uuid4()
        memory_id_2 = uuid4()

        shared_ledger = Ledger(shared_engine)

        # Shared has TWO PEVR cycles; isolated has only the first
        # one (the migration paused mid-copy — divergence simulated).
        await shared_ledger.write(
            company_id=company_id, **_propose_args(memory_id_1),
        )
        # Snapshot cycle 1 onto isolated.
        await _copy_entries(shared_engine, isolated_engine, company_id)
        # Continue cycle 2 only on shared.
        await shared_ledger.write(
            company_id=company_id, **_propose_args(memory_id_2),
        )

        window_start = datetime.now(UTC) - timedelta(hours=1)
        window_end = datetime.now(UTC) + timedelta(hours=1)
        diff = await validate_parallel_replay(
            tenant_slug="globex",
            shared_engine=shared_engine,
            isolated_engine=isolated_engine,
            company_id=company_id,
            window_start=window_start,
            window_end=window_end,
        )

        assert diff.is_consistent is False
        assert diff.shared_entry_count == 8  # 2 cycles × 4 phases
        assert diff.isolated_entry_count == 4
        assert len(diff.inconsistency_reasons) >= 1
        # At least one reason explains the count mismatch.
        assert any(
            "entry count mismatch" in r
            for r in diff.inconsistency_reasons
        )
    finally:
        await shared_engine.dispose()
        await isolated_engine.dispose()


@pytest.mark.asyncio
async def test_parallel_replay_empty_window_consistent() -> None:
    """Empty window on both sides is vacuously consistent."""
    shared_engine = await _make_engine()
    isolated_engine = await _make_engine()
    try:
        company_id = uuid4()

        # Look at a window in the past where nothing happened.
        window_start = datetime(2020, 1, 1, tzinfo=UTC)
        window_end = datetime(2020, 1, 2, tzinfo=UTC)
        diff = await validate_parallel_replay(
            tenant_slug="initech",
            shared_engine=shared_engine,
            isolated_engine=isolated_engine,
            company_id=company_id,
            window_start=window_start,
            window_end=window_end,
        )

        assert diff.is_consistent is True
        assert diff.shared_entry_count == 0
        assert diff.isolated_entry_count == 0
        assert diff.shared_terminal_hash is None
        assert diff.isolated_terminal_hash is None
        assert diff.kind_counts_shared == {}
        assert diff.kind_counts_isolated == {}
        assert diff.inconsistency_reasons == ()
    finally:
        await shared_engine.dispose()
        await isolated_engine.dispose()


@pytest.mark.asyncio
async def test_parallel_replay_empty_window_on_one_side_inconsistent() -> None:
    """One side empty, the other with entries → inconsistent (drift)."""
    shared_engine = await _make_engine()
    isolated_engine = await _make_engine()
    try:
        company_id = uuid4()
        memory_id = uuid4()

        shared_ledger = Ledger(shared_engine)
        await shared_ledger.write(
            company_id=company_id, **_propose_args(memory_id),
        )

        window_start = datetime.now(UTC) - timedelta(hours=1)
        window_end = datetime.now(UTC) + timedelta(hours=1)
        diff = await validate_parallel_replay(
            tenant_slug="acme",
            shared_engine=shared_engine,
            isolated_engine=isolated_engine,
            company_id=company_id,
            window_start=window_start,
            window_end=window_end,
        )

        assert diff.is_consistent is False
        assert diff.shared_entry_count == 4
        assert diff.isolated_entry_count == 0
        # Terminal-hash mismatch is one of the reasons.
        assert any(
            "terminal hash mismatch" in r
            for r in diff.inconsistency_reasons
        )
    finally:
        await shared_engine.dispose()
        await isolated_engine.dispose()


@pytest.mark.asyncio
async def test_parallel_replay_rejects_naive_window() -> None:
    """``window_start`` / ``window_end`` must be tz-aware."""
    shared_engine = await _make_engine()
    isolated_engine = await _make_engine()
    try:
        company_id = uuid4()
        naive = datetime(2026, 1, 1)
        aware = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError):
            await validate_parallel_replay(
                tenant_slug="acme",
                shared_engine=shared_engine,
                isolated_engine=isolated_engine,
                company_id=company_id,
                window_start=naive,
                window_end=aware,
            )
        with pytest.raises(ValueError):
            await validate_parallel_replay(
                tenant_slug="acme",
                shared_engine=shared_engine,
                isolated_engine=isolated_engine,
                company_id=company_id,
                window_start=aware,
                window_end=naive,
            )
    finally:
        await shared_engine.dispose()
        await isolated_engine.dispose()
