"""Multi-tenant isolation: two companies sharing a DB do not interfere.

Per Wave-2 review: logical partitioning (uniqueness on `company_id`, indexes)
is sufficient for v-demo. Native Postgres declarative partitioning is v1.1.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.repo import fetch_entries
from wormbase_ledger.verify import verify_company_chain
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_two_companies_do_not_interfere(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    c1, c2 = uuid4(), uuid4()
    # Interleave writes: c1, c2, c1, c2, c1 → c1 has 12 entries, c2 has 8.
    for cid in (c1, c2, c1, c2, c1):
        async with session_scope(engine) as session:
            await write_primitive(
                session,
                company_id=cid,
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

    async with session_scope(engine) as session:
        rows1 = await fetch_entries(session, c1)
        rows2 = await fetch_entries(session, c2)

    assert len(rows1) == 12 and len(rows2) == 8
    assert [r["seq"] for r in rows1] == list(range(1, 13))
    assert [r["seq"] for r in rows2] == list(range(1, 9))

    r1 = await verify_company_chain(engine, c1)
    r2 = await verify_company_chain(engine, c2)
    assert r1.ok and r2.ok
