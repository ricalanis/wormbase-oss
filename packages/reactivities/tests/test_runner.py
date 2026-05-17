"""Runner: end-to-end fire path + ledger writes + reset detection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityRegistry,
    ReactivityResult,
    ReactivityRunner,
    ReactivityScope,
)


def _now_factory(state: dict):
    def _now() -> datetime:
        return state["now"]

    return _now


class _CountingReactivity:
    """Reactivity that records the seqs it fired against."""

    id = "counter"
    name = "Counter"
    description = ""
    scope: ReactivityScope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        self.condition = AlwaysAllow()
        self.seqs: list[int] = []

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        self.seqs.append(int(entry.get("seq", 0)))
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="counted")],
            novelty_key=f"seq-{entry.get('seq')}",
            budget_used={"per_tenant": 1},
        )


async def _seed_chat_received(
    ledger: InMemoryLedger, company_id: UUID, seq_hint: int,
) -> None:
    """Write a chat_received PEVR cycle through the InMemoryLedger.

    seq_hint is unused (the in-memory ledger assigns seqs); kept for
    test readability.
    """
    args = {
        "channel_id": "C0",
        "message_id": str(uuid4()),
        "sender_person": str(uuid4()),
        "text": f"hi {seq_hint}",
        "classification": "internal",
        "platform": "slack",
        "platform_user_id": f"U-{seq_hint}",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": args["message_id"],
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": args["message_id"],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_runner_dispatches_new_entries(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    counter = _CountingReactivity()
    registry.register(counter)
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await _seed_chat_received(ledger, company_id, 1)
    await _seed_chat_received(ledger, company_id, 2)
    fired = await runner.run_once()
    assert fired == 2
    # Each chat seeds a PEVR (4 entries); the runner sees the execute row
    # of each (seq 2 and 6 in a 1-based ledger).
    assert len(counter.seqs) == 2


async def test_runner_skips_already_processed_entries(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    counter = _CountingReactivity()
    registry.register(counter)
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await _seed_chat_received(ledger, company_id, 1)
    fires_first = await runner.run_once()
    assert fires_first == 1
    # No new entries — second pass should be a no-op.
    fires_second = await runner.run_once()
    assert fires_second == 0
    assert len(counter.seqs) == 1


async def test_runner_handles_empty_ledger(ledger, company_id: UUID) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    registry.register(_CountingReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
    )
    fires = await runner.run_once()
    assert fires == 0
    assert runner.last_seq == 0


async def test_runner_rewinds_on_tenant_reset(company_id: UUID) -> None:
    """Swap the ledger handle for a fresh one (max_seq=0 < runner cursor)."""
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    ledger_a = InMemoryLedger()
    registry = ReactivityRegistry(
        ledger=ledger_a, company_id=company_id, now=_now_factory(state),
    )
    counter = _CountingReactivity()
    registry.register(counter)
    runner = ReactivityRunner(
        ledger=ledger_a, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await _seed_chat_received(ledger_a, company_id, 1)
    await runner.run_once()
    assert runner.last_seq > 0
    pre_reset_count = len(counter.seqs)

    # Simulate reset by swapping ledger handles.
    ledger_b = InMemoryLedger()
    runner._ledger = ledger_b  # noqa: SLF001
    registry._ledger = ledger_b  # noqa: SLF001
    await _seed_chat_received(ledger_b, company_id, 99)
    await runner.run_once()
    # Cursor rewound + new entry processed.
    assert len(counter.seqs) == pre_reset_count + 1


async def test_runner_only_fires_active_reactivities(
    ledger, company_id: UUID,
) -> None:
    state = {"now": datetime(2026, 4, 28, 10, 0, tzinfo=UTC)}
    registry = ReactivityRegistry(
        ledger=ledger, company_id=company_id, now=_now_factory(state),
    )
    counter = _CountingReactivity()
    # Register in proposed state — should not fire.
    registry.register(counter, initial_state="proposed")
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
    )
    await _seed_chat_received(ledger, company_id, 1)
    fires = await runner.run_once()
    assert fires == 0
    # After confirm, should fire.
    await registry.confirm("counter", confirmed_by=uuid4())
    await _seed_chat_received(ledger, company_id, 2)
    fires_after = await runner.run_once()
    assert fires_after == 1
