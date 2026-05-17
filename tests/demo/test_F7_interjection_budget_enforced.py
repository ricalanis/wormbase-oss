"""F7 demo gate: ≤3 clarifying questions per channel per UTC day.

The demo's "responsiveness without spam" promise. Drives the
InterjectionGate beyond budget and asserts the 4th call is blocked
with a `gate_fired` ledger entry naming the budget exhaustion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from wormbase_governance import InterjectionGate
from wormbase_ledger import InMemoryLedger


class _FrozenClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def tick(self, **kw) -> None:  # type: ignore[no-untyped-def]
        self._now += timedelta(**kw)


@pytest.mark.asyncio
async def test_F7_interjection_budget_enforced() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()
    clock = _FrozenClock(datetime(2026, 4, 30, 9, 0, tzinfo=UTC))
    gate = InterjectionGate(ledger, company_id, clock=clock, limit=3)

    decisions = []
    for _ in range(4):
        clock.tick(minutes=1)
        decisions.append(await gate.allow("C-demo", "clarification"))

    assert decisions == [True, True, True, False], (
        f"F7 GATE FAILED: expected [T,T,T,F], got {decisions}"
    )

    rows = await ledger.fetch(company_id)
    blocked = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_gate_fired"
        and r["payload"]["args"].get("gate") == "interjection"
        and r["payload"]["args"].get("outcome") == "blocked"
    ]
    assert len(blocked) == 1, (
        f"F7 GATE FAILED: expected exactly 1 interjection block; got {len(blocked)}"
    )
