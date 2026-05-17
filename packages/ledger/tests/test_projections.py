"""Tests for projection builders: sources, memory, kpi, ramp."""

from __future__ import annotations

from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_sources_projection_reflects_source_proposed(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(source_id),
                "reason": "drop",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(source_id),
                    "source_kind": "file",
                    "uri": "s3://b/x.csv",
                    "added_via_flow": "drop_and_profile",
                    "suggested_domain": "finance",
                    "suggested_classification": "internal",
                },
                "result_ref": "ok",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.sources) == 1
    assert proj.sources[0]["source_id"] == source_id
    assert proj.sources[0]["added_via_flow"] == "drop_and_profile"
    assert proj.sources[0]["status"] == "proposed"


@pytest.mark.asyncio
async def test_ramp_projection_has_six_axes(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)
    axes = {r["axis"] for r in proj.ramp}
    assert axes == {
        "ontology",
        "schema",
        "business_definitions",
        "kpi_relational",
        "conversational",
        "operational",
    }
    for r in proj.ramp:
        assert r["value"] == "0"


@pytest.mark.asyncio
async def test_memory_projection_records_writes(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    memory_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(memory_id),
                "reason": "concept",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(memory_id),
                    "content": "annual = 12 month commit",
                    "tags": ["concept", "pricing"],
                },
                "result_ref": "ok",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.memory) == 1
    assert proj.memory[0]["content"] == "annual = 12 month commit"
    assert proj.memory[0]["tags"] == ["concept", "pricing"]
