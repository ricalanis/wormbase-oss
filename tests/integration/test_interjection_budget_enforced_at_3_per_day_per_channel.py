"""L5 integration: ≤3 clarifying questions per channel per UTC day.

Drives the ``InterjectionGate.allow`` 4 times in one channel within a
single day window. The first 3 must return True (and write a
`clarify_asked` memory entry); the 4th must return False AND write a
`gate_fired` entry with reason mentioning budget exhaustion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


class _FrozenClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def tick(self, **kw) -> datetime:  # type: ignore[no-untyped-def]
        self._now += timedelta(**kw)
        return self._now


@pytest.mark.asyncio
async def test_fourth_clarification_in_one_day_is_blocked_with_gate_fired(
    integration_ledger, integration_company_id,
) -> None:
    from wormbase_governance import InterjectionGate

    clock = _FrozenClock(datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC))
    gate = InterjectionGate(
        integration_ledger, integration_company_id, clock=clock, limit=3,
    )

    channel_id = "C0BUDGET"
    decisions = []
    for i in range(4):
        # advance 1 minute between calls so the entries have distinct ts
        clock.tick(minutes=1)
        decisions.append(await gate.allow(channel_id, "clarification"))

    assert decisions[:3] == [True, True, True], (
        f"first three clarifications should be allowed, got {decisions}"
    )
    assert decisions[3] is False, (
        f"fourth clarification should be blocked, got {decisions[3]}"
    )

    # The gate_fired entry on the 4th call must mention budget/interjection.
    rows = await integration_ledger.fetch(integration_company_id)
    gate_fires = [
        r["payload"]["args"] for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_gate_fired"
        and r["payload"]["args"].get("gate") == "interjection"
    ]
    assert gate_fires, "no interjection gate_fired entry was written"
    last = gate_fires[-1]
    assert last["outcome"] == "blocked"
    assert last["channel_id"] == channel_id
    assert last["limit"] == 3
    assert last["current_count"] == 3
