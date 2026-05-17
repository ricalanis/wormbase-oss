"""O-A1: pin in-memory replay must handle non-source entry kinds.

`InMemoryLedger.replay()` historically initialized a hand-rolled state-dict with
only 5 keys (`sources`, `memory`, `kpi_nodes`, `chat_count`, `resolve_count`),
while `build_projections` (the DB-backed fold) initializes 14 keys including
`persons`, `person_identities`, `installs`, `roles`, `data_products`, etc.

Folding a `propose/execute/verify/resolve` cycle for `emit_person_proposed`
through the in-memory path raises `KeyError: 'persons'` from `_apply_execute`
because the seed-state lacks the slot.

Fix: extract `_initial_projection_state()` and call from both paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_in_memory_replay_handles_person_proposed() -> None:
    mem = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()
    tenant_id = company_id  # tenant_id == company_id for ledger-scoping

    res = await mem.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(person_id),
            "reason": "auto-discovered from chatter",
            "proposed_by": "worm",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": {
                "person_id": str(person_id),
                "tenant_id": str(tenant_id),
                "name": "Bob",
                "email": "bob@example.co",
                "platform": "slack",
                "platform_user_id": "U-bob",
                "proposed_by": "worm",
            },
            "result_ref": "r",
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )
    assert len(res.entry_ids) == 4

    snap = await mem.replay(company_id, datetime.now(UTC) + timedelta(hours=1))
    # Pre-fix: this assertion is unreachable — the replay raises
    # KeyError: 'persons' from _apply_execute. Post-fix: persons row exists.
    assert len(snap.projections.persons) == 1
    assert snap.projections.persons[0]["name"] == "Bob"
