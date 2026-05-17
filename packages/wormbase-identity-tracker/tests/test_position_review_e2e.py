"""End-to-end test for the position auto-confirm UX (Phase 2 Task 2C).

Exercises the full chain:

    1. emit_chat_received (multiple) → Person's chat history fills
    2. PositionInferenceReactivity.fire() crosses threshold and
       writes a propose_position PEVR cycle
    3. The optimistic-write fold lands the inferred position on the
       Person row of the projection
    4. write_actions.confirm_position_proposal lands the admin
       confirm-step entry
    5. The full chain replays cleanly (hash-chain valid, fold
       deterministic).

Does NOT spin up an HTTP server — the worm-core HTTP layer is exercised
in apps/worm-core/tests/test_http_api_position_review.py. This test
validates the wire-shape contract from inside the Reactivity all the
way to the projection state, which is the e2e shape the Wave-H plan
calls for ("chat → propose → confirm → projection updates").
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload, PersonProposedPayload
from wormbase_ledger.hash_chain import verify_chain
from wormbase_ledger.projections.builder import _apply_execute


pytestmark = pytest.mark.asyncio


def _empty_state() -> dict[str, Any]:
    return {
        "persons": {},
        "person_identities": {},
        "sources": {},
        "memory": [],
        "kpi_nodes": {},
        "installs": {},
        "roles": {},
        "data_products": {},
        "data_product_runs": {},
        "data_product_consumption": [],
        "notebooks": {},
        "notebook_runs": {},
        "setup_progress": {},
        "mcp_calls": [],
        "topics": {},
    }


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    sender_person: UUID,
    text: str,
) -> str:
    payload = ChatReceivedPayload(
        channel_id="C0",
        message_id=str(uuid4()),
        sender_person=sender_person,
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": args["message_id"],
            "reason": "test seed",
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
    return args["message_id"]


async def _seed_person_proposed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    name: str,
) -> None:
    payload = PersonProposedPayload(
        person_id=person_id,
        tenant_id=company_id,
        name=name,
        email=f"{name.lower()}@x.co",
        platform="slack",
        platform_user_id=f"U-{name.lower()}",
        proposed_by="worm",
        position=None,
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(person_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_person_proposed",
            "args": args,
            "result_ref": str(person_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _drive_position_reactivity(
    ledger: InMemoryLedger,
    company_id: UUID,
) -> None:
    from wormbase_identity_tracker.reactivities import (
        PositionInferenceReactivity,
    )
    from wormbase_reactivities import ReactivityRegistry, ReactivityRunner

    registry = ReactivityRegistry(ledger=ledger, company_id=company_id)
    registry.register(PositionInferenceReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=company_id, registry=registry,
        poll_interval_s=0.01,
    )
    await runner.run_once()


def _fold_persons(rows: list[dict[str, Any]]) -> dict[str, Any]:
    state = _empty_state()
    for r in rows:
        if r.get("kind") == "execute":
            _apply_execute(r, state)
    return state["persons"]


async def test_chat_propose_confirm_e2e_chain(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Full chain: chat → propose → confirm → projection state.

    1. Seed a Person and 3 chat_received entries with data-engineer
       signal tokens.
    2. Drive PositionInferenceReactivity once. It should fire and
       write a propose_position PEVR cycle.
    3. Fold the projection — Person row carries the inferred position.
    4. Call write_actions.confirm_position_proposal as the admin would
       from the /people/proposals queue.
    5. Re-fold the projection — Person row keeps the position
       (confirm is a no-op fold; the audit anchor is enough).
    6. Verify hash chain stays valid across all 12+ entries.
    """
    from wormbase_core import write_actions

    pid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Dee")

    # Three Data-Engineer-flavored chats. The DE position has 5 patterns
    # ("why is", "when did this break", "what changed", "schema",
    # "query cost"); 3 hits → confidence 3/5 = 0.6 ≥ 0.5 threshold.
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="why is the bronze→silver pipeline lagging?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="what changed in the schema overnight?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="query cost spiked on the orders join, fyi",
    )

    # 1+3 = 4 PEVR cycles seeded so far → 16 ledger entries.
    rows_before = await ledger.fetch(company_id)
    assert len(rows_before) == 16

    # ---------- (2) drive the Reactivity ----------
    await _drive_position_reactivity(ledger, company_id)

    rows_after_propose = await ledger.fetch(company_id)
    proposed_rows = [
        r for r in rows_after_propose
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_position_proposed"
    ]
    assert len(proposed_rows) == 1, (
        "PositionInferenceReactivity should have crossed threshold once"
    )
    proposed_args = proposed_rows[0]["payload"]["args"]
    inferred_position = proposed_args["position"]
    assert proposed_args["person_id"] == str(pid)
    assert proposed_args["confidence"] >= 0.5

    # ---------- (3) optimistic-write fold ----------
    persons = _fold_persons(rows_after_propose)
    assert persons[str(pid)]["position"] == inferred_position

    # ---------- (4) admin confirms via write_actions ----------
    admin = uuid4()
    await write_actions.confirm_position_proposal(
        ledger, company_id,
        person_id=pid, position=inferred_position, confirmed_by=admin,
    )

    rows_after_confirm = await ledger.fetch(company_id)
    confirmed_rows = [
        r for r in rows_after_confirm
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_position_confirmed"
    ]
    assert len(confirmed_rows) == 1
    assert confirmed_rows[0]["payload"]["args"]["person_id"] == str(pid)
    assert confirmed_rows[0]["payload"]["args"]["confirmed_by"] == str(admin)

    # ---------- (5) projection still carries the position ----------
    persons_after_confirm = _fold_persons(rows_after_confirm)
    assert persons_after_confirm[str(pid)]["position"] == inferred_position

    # ---------- (6) hash chain holds across everything ----------
    ok, broken_at = verify_chain(rows_after_confirm)
    assert ok, f"chain broken at seq {broken_at}"


async def test_chat_propose_reject_clears_position_e2e(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Reject path: confirm-step's sibling.

    Same setup as the confirm e2e, but the admin clicks Reject instead.
    The projection should clear the optimistic position write and the
    Reactivity's dedup gate should free the Person for re-proposal.
    """
    from wormbase_core import write_actions

    pid = uuid4()
    await _seed_person_proposed(ledger, company_id, person_id=pid, name="Eve")

    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="why is the silver table behind?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="what changed in the data model?",
    )
    await _seed_chat_received(
        ledger, company_id, sender_person=pid,
        text="query cost jumped 4x today",
    )

    await _drive_position_reactivity(ledger, company_id)

    rows = await ledger.fetch(company_id)
    proposed = [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_position_proposed"
    ]
    assert len(proposed) == 1
    inferred = proposed[0]["payload"]["args"]["position"]

    persons = _fold_persons(rows)
    assert persons[str(pid)]["position"] == inferred

    admin = uuid4()
    await write_actions.reject_position_proposal(
        ledger, company_id,
        person_id=pid, position=inferred, rejected_by=admin,
        reason="joined as analyst, not engineer",
    )

    rows_after_reject = await ledger.fetch(company_id)
    rejected = [
        r for r in rows_after_reject
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_position_rejected"
    ]
    assert len(rejected) == 1
    args = rejected[0]["payload"]["args"]
    assert args["person_id"] == str(pid)
    assert args["reason"] == "joined as analyst, not engineer"

    # Optimistic write cleared.
    persons_after = _fold_persons(rows_after_reject)
    assert persons_after[str(pid)]["position"] is None

    ok, _ = verify_chain(rows_after_reject)
    assert ok
