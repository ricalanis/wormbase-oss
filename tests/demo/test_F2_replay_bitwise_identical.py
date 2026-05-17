"""F2 demo gate: replay produces bitwise-identical projection hashes.

Drives 10 deterministic events through the full WormCore stack, then
calls `ledger.replay()` 10 times and asserts every snapshot's
`hash_of_projections` is the SAME bytes object. Drift = fail.

This is a pure-Python L6 gate; no Docker required. The L5 mirror is
tests/integration/test_replay_determinism_across_full_stack.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from wormbase_core.service import build_worm_core
from wormbase_ledger import InMemoryLedger


@pytest.mark.reproducibility
@pytest.mark.asyncio
async def test_F2_replay_bitwise_identical() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()
    worm = await build_worm_core(
        ledger, company_id,
        domain_pack="saas",
        enable_lurker=False, enable_cloud_classifier=False,
    )
    t0 = datetime(2026, 4, 30, 12, tzinfo=UTC)
    for i in range(10):
        await worm.pipeline.process(
            {
                "type": "channel_message",
                "ts": (t0 + timedelta(seconds=i)).timestamp(),
                "channel_id": "C-demo",
                "user_id": "U-demo",
                "text": f"deterministic event {i}",
                "message_id": f"m-{i:02d}",
                "company_id": str(company_id),
                "payload": {"i": i},
            }
        )
    until = t0 + timedelta(minutes=10)
    hashes = set()
    for _ in range(10):
        snap = await ledger.replay(company_id, until)
        hashes.add(snap.hash_of_projections)
    assert len(hashes) == 1, (
        f"F2 GATE FAILED: replay drifted across 10 invocations: {hashes}"
    )
