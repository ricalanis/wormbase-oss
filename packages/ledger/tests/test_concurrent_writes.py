"""Concurrent writer test: many concurrent calls to write_primitive against
the same company_id must produce a contiguous (1..N*4) seq sequence with
an intact hash chain.

On Postgres this exercises the SELECT … FOR UPDATE row lock in
write_primitive._tail. On SQLite, the database is single-writer so writes
serialize at the OS level; either way the invariant we care about is that
no two writers ever produce the same `seq` and that prev_hash always
points at the actual previous entry.

Notes
-----
- We use a smaller fan-out (10 concurrent writes) so this is fast on SQLite.
- For production-equivalent stress (20+ writers with row locks), point
  WORMBASE_TEST_DB_URL at a Postgres instance.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.repo import fetch_entries
from wormbase_ledger.verify import verify_company_chain
from wormbase_ledger.write_primitive import write_primitive


async def _one(engine, company_id) -> None:
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
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {"memory_id": str(uuid4()), "content": "c", "tags": []},
                "result_ref": "r",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )


@pytest.mark.asyncio
async def test_concurrent_writes_preserve_chain(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    n = 10  # 10 * 4 entries = 40 rows

    # On SQLite, fully concurrent writes can collide on the BEGIN IMMEDIATE
    # lock. We retry transient conflicts; the contract under test is the
    # final state (seq sequence + chain integrity), not absence of retries.
    async def _safe_one() -> None:
        # SQLite has no row-level locking; concurrent writers can read the
        # same tail seq and collide on the (company_id, seq) unique
        # constraint. The constraint itself is the canonical guard — we
        # retry until success. On Postgres, the SELECT … FOR UPDATE in
        # write_primitive._tail removes this race entirely so retries are
        # essentially never needed.
        for attempt in range(64):
            try:
                await _one(engine, company_id)
                return
            except Exception as exc:
                msg = str(exc).lower()
                retriable = (
                    "locked" in msg
                    or "busy" in msg
                    or "concurrent" in msg
                    or "unique constraint" in msg
                )
                if retriable:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                raise
        raise RuntimeError(
            "write_primitive could not acquire DB lock after 64 retries"
        )

    await asyncio.gather(*[_safe_one() for _ in range(n)])

    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)

    assert [r["seq"] for r in rows] == list(range(1, n * 4 + 1))
    report = await verify_company_chain(engine, company_id)
    assert report.ok is True
