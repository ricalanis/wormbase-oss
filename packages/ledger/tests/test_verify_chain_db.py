"""Tests for `verify_company_chain` — full-DB hash chain walk + tamper
detection."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import update
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.schema import ledger
from wormbase_ledger.verify import verify_company_chain
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_verify_passes_on_intact_chain(test_database_url: str) -> None:
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
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {"memory_id": str(uuid4()), "content": "c", "tags": []},
                "result_ref": "r",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )
    report = await verify_company_chain(engine, company_id)
    assert report.ok is True
    assert report.entries_checked == 4
    assert report.broken_at is None


@pytest.mark.asyncio
async def test_verify_detects_payload_tamper(test_database_url: str) -> None:
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
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {"memory_id": str(uuid4()), "content": "c", "tags": []},
                "result_ref": "r",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )
    # Tamper: rewrite the execute row's payload without recomputing hash.
    async with session_scope(engine) as session:
        await session.execute(
            update(ledger)
            .where((ledger.c.company_id == company_id) & (ledger.c.kind == "execute"))
            .values(
                payload={
                    "tool": "tampered",
                    "args": {},
                    "result_ref": "x",
                    "propose_entry_id": "00000000-0000-0000-0000-000000000000",
                }
            )
        )
    report = await verify_company_chain(engine, company_id)
    assert report.ok is False
    assert report.broken_at == 1
