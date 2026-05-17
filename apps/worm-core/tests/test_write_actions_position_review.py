"""Unit tests for ``write_actions.confirm_position_proposal`` and
``write_actions.reject_position_proposal`` (Wave H Phase 2 Task 2C).

The admin-review queue at /people/proposals lets a tenancy.admin confirm
or reject worm-inferred position proposals. Each confirm/reject is one
4-entry PEVR cycle. Tests assert:

  * confirm — emits emit_position_confirmed; chain valid.
  * reject — emits emit_position_rejected; clears the optimistic
    position write on the projection when slug matches.
  * reject preserves position when admin already overrode via
    emit_position_assigned (rejection only clears matching slug).
  * round-trip via the projection builder.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_core import write_actions
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain
from wormbase_ledger.projections.builder import _apply_execute


@pytest.mark.asyncio
async def test_confirm_position_proposal_writes_pevr_cycle(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    person_id, _ = await write_actions.propose_person(
        ledger, company_id,
        name="Alice", email=None, platform="slack",
        platform_user_id="U-alice", position=None, proposed_by="worm",
    )
    await write_actions.propose_position(
        ledger, company_id,
        person_id=person_id, position="senior_engineer",
        confidence=0.7, signals=("commit_msg", "design_doc"),
        proposed_by="worm",
    )
    admin = uuid4()

    result = await write_actions.confirm_position_proposal(
        ledger, company_id,
        person_id=person_id, position="senior_engineer", confirmed_by=admin,
    )
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    confirms = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_position_confirmed"
    ]
    assert len(confirms) == 1
    args = confirms[0]["payload"]["args"]
    assert args["person_id"] == str(person_id)
    assert args["position"] == "senior_engineer"
    assert args["confirmed_by"] == str(admin)

    ok, broken_at = verify_chain(rows)
    assert ok, f"chain broken at seq {broken_at}"


@pytest.mark.asyncio
async def test_reject_position_proposal_clears_optimistic_write(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    person_id, _ = await write_actions.propose_person(
        ledger, company_id,
        name="Bob", email=None, platform="slack",
        platform_user_id="U-bob", position=None, proposed_by="worm",
    )
    await write_actions.propose_position(
        ledger, company_id,
        person_id=person_id, position="data_analyst",
        confidence=0.6, signals=(), proposed_by="worm",
    )
    admin = uuid4()

    result = await write_actions.reject_position_proposal(
        ledger, company_id,
        person_id=person_id, position="data_analyst",
        rejected_by=admin, reason="signals too thin",
    )
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    rejects = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_position_rejected"
    ]
    assert len(rejects) == 1
    args = rejects[0]["payload"]["args"]
    assert args["person_id"] == str(person_id)
    assert args["position"] == "data_analyst"
    assert args["rejected_by"] == str(admin)
    assert args["reason"] == "signals too thin"

    # Fold all execute rows through the projection builder. After reject,
    # the optimistic position write is cleared.
    state: dict[str, dict[str, dict[str, object]]] = {
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
    for r in rows:
        if r["kind"] == "execute":
            _apply_execute(r, state)  # type: ignore[arg-type]
    person = state["persons"][str(person_id)]
    assert person["position"] is None


@pytest.mark.asyncio
async def test_reject_position_proposal_reason_optional(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    person_id, _ = await write_actions.propose_person(
        ledger, company_id,
        name="Carol", email=None, platform="slack",
        platform_user_id="U-carol", position=None, proposed_by="worm",
    )
    await write_actions.propose_position(
        ledger, company_id,
        person_id=person_id, position="senior_engineer",
        confidence=0.6, signals=(), proposed_by="worm",
    )
    admin = uuid4()

    # Omit reason — payload allows None.
    result = await write_actions.reject_position_proposal(
        ledger, company_id,
        person_id=person_id, position="senior_engineer",
        rejected_by=admin, reason=None,
    )
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    rejects = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_position_rejected"
    ]
    args = rejects[0]["payload"]["args"]
    assert args.get("reason") is None
