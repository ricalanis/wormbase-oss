"""Acceptance gate: replay produces bitwise-identical projection hashes
across 10 invocations against the same inputs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.replay import replay
from wormbase_ledger.write_primitive import write_primitive


@pytest.mark.reproducibility
@pytest.mark.asyncio
async def test_replay_is_bitwise_identical_across_10_invocations(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    t0 = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)

    seeds = [
        (
            "source_proposed",
            "emit_source_proposed",
            {
                "source_id": str(uuid4()),
                "source_kind": "file",
                "uri": "s3://b/a.csv",
                "added_via_flow": "drop_and_profile",
                "suggested_domain": "finance",
                "suggested_classification": "internal",
            },
        ),
        (
            "source_proposed",
            "emit_source_proposed",
            {
                "source_id": str(uuid4()),
                "source_kind": "database",
                "uri": "postgres://h/db",
                "added_via_flow": "credential_offered_in_dm",
                "suggested_domain": "product",
                "suggested_classification": "internal",
            },
        ),
        (
            "memory_written",
            "emit_memory_written",
            {
                "memory_id": str(uuid4()),
                "content": "annual=12mo",
                "tags": ["concept"],
            },
        ),
        (
            "memory_written",
            "emit_memory_written",
            {
                "memory_id": str(uuid4()),
                "content": "mrr excludes churn",
                "tags": ["concept", "kpi"],
            },
        ),
        (
            "source_proposed",
            "emit_source_proposed",
            {
                "source_id": str(uuid4()),
                "source_kind": "blob",
                "uri": "s3://b/y.parquet",
                "added_via_flow": "kpi_gap_triggered",
                "suggested_domain": "ops",
                "suggested_classification": "internal",
            },
        ),
    ]

    for i, (target, tool, args) in enumerate(seeds):
        async with session_scope(engine) as session:
            await write_primitive(
                session,
                company_id=company_id,
                propose={
                    "target_kind": target,
                    "ref_id": str(uuid4()),
                    "reason": "seed",
                    "proposed_by": "test",
                },
                execute_fn=(lambda tool=tool, args=args, i=i: {
                    "tool": tool, "args": args, "result_ref": f"r{i}"
                }),
                verify_fn=lambda _r: {"checks": [], "passed": True},
                resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
                timestamp=t0 + timedelta(minutes=i),
            )

    until = t0 + timedelta(hours=1)
    hashes: set[bytes] = set()
    for _ in range(10):
        snap = await replay(engine, company_id, until)
        hashes.add(snap.hash_of_projections)

    assert len(hashes) == 1, f"replay drifted across 10 runs: {hashes}"
