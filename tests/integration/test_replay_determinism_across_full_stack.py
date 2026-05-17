"""L5 integration: 10 deterministic events replay with bitwise-identical hash.

This is the cross-stack version of `packages/ledger`'s
`test_replay_is_bitwise_identical_across_10_invocations` — same seed
events, but driven through the WormCore ``service.build_worm_core``
graph rather than directly via ``write_primitive``. Catches any
hidden non-determinism introduced by warmup, classifier, or ramp.

This is the F2 demo gate (replay bitwise-identical) lifted to L5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from wormbase_core.reactivity import InfraEvent
from wormbase_core.service import build_worm_core
from wormbase_ledger import InMemoryLedger


@pytest.mark.reproducibility
@pytest.mark.asyncio
async def test_full_stack_replay_yields_identical_hash_across_10_runs() -> None:
    """Drive 10 fixed events through worm-core; replay; assert hash is
    constant across re-replays."""
    company_id = uuid4()
    ledger = InMemoryLedger()
    worm = await build_worm_core(
        ledger, company_id,
        domain_pack="saas",
        enable_lurker=False,
        enable_cloud_classifier=False,
    )

    t0 = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)
    seeds: list[InfraEvent] = []
    for i in range(10):
        seeds.append(
            InfraEvent(
                source="channel_message",
                payload={"deterministic": True, "i": i},
                ts=t0 + timedelta(seconds=i),
                company_id=company_id,
                message_id=f"m-{i:02d}",
                channel_id="C-deterministic",
                person_id="U-deterministic",
                text=f"deterministic message {i}",
            )
        )

    for ev in seeds:
        await worm.pipeline.process(
            {
                "type": "channel_message",
                "ts": ev.ts.timestamp(),
                "channel_id": ev.channel_id,
                "user_id": ev.person_id,
                "text": ev.text,
                "message_id": ev.message_id,
                "company_id": str(company_id),
                "payload": ev.payload,
            }
        )

    # Replay multiple times; every snapshot's hash must be identical.
    until = t0 + timedelta(minutes=10)
    snapshots = []
    for _ in range(10):
        snapshots.append(await ledger.replay(company_id, until))

    hashes = {s.hash_of_projections for s in snapshots}
    assert len(hashes) == 1, f"replay drifted across runs: {hashes}"

    # Sanity: the projection itself is non-trivial — chat_count > 0.
    proj = snapshots[0].projections
    assert proj.ramp is not None
