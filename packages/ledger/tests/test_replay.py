from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.replay import replay
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.asyncio
async def test_replay_returns_projections_snapshot(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    sid = uuid4()
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(sid),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(sid),
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

    snap = await replay(engine, company_id, datetime.now(UTC) + timedelta(hours=1))
    assert snap.hash_of_projections is not None
    assert len(snap.hash_of_projections) == 32
    assert len(snap.projections.sources) == 1


@pytest.mark.asyncio
async def test_replay_respects_until_ts(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    sid = uuid4()
    t0 = datetime.now(UTC)

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(sid),
                "reason": "r",
                "proposed_by": "w",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(sid),
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
            timestamp=t0 + timedelta(minutes=10),
        )

    snap = await replay(engine, company_id, t0 - timedelta(minutes=1))
    assert snap.projections.sources == []
