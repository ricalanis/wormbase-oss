"""Unit tests for ``write_actions.bulk_confirm_persons`` (W2.A6).

The orchestrator confirms a batch of proposed Persons in a single API
call by running one independent ``confirm_person`` PEVR cycle per id.
These tests assert:

  * happy-path — N proposals → 4N ledger entries (one PEVR cycle each),
    one ``emit_person_confirmed`` per Person, returned envelope shape is
    ``{confirmed_count, person_ids, entry_ids}``.
  * de-duplication — duplicate ids in the input list collapse to one
    confirmation each (the API is idempotent on its inputs).
  * empty input — the orchestrator raises ``ValueError`` so the API
    layer can map to 422; a no-op batch is a client bug.
  * hash chain — the resulting ledger remains hash-chain valid after
    the bulk operation.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_core import write_actions
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


async def _seed_proposed_persons(
    ledger: InMemoryLedger, company_id: UUID, count: int,
) -> list[UUID]:
    pids: list[UUID] = []
    for i in range(count):
        pid, _ = await write_actions.propose_person(
            ledger, company_id,
            name=f"Person {i}",
            email=f"p{i}@x.co",
            platform="slack",
            platform_user_id=f"U-p{i}",
            position=None,
            proposed_by="worm",
        )
        pids.append(pid)
    return pids


@pytest.mark.asyncio
async def test_bulk_confirm_writes_one_pevr_per_person(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    pids = await _seed_proposed_persons(ledger, company_id, count=4)
    admin = pids[0]  # any UUID will do as the actor

    result = await write_actions.bulk_confirm_persons(
        ledger, company_id, person_ids=pids, confirmed_by=admin,
    )
    assert result["confirmed_count"] == 4
    assert result["person_ids"] == [str(p) for p in pids]
    # Each confirm_person is a 4-entry PEVR cycle.
    assert len(result["entry_ids"]) == 4 * 4

    # Verify exactly one emit_person_confirmed landed for each id.
    rows = await ledger.fetch(company_id)
    confirmed_ids = [
        r["payload"]["args"]["person_id"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_person_confirmed"
    ]
    assert sorted(confirmed_ids) == sorted(str(p) for p in pids)

    # Hash chain remains intact.
    ok, broken_at = verify_chain(rows)
    assert ok, f"chain broken at seq {broken_at}"


@pytest.mark.asyncio
async def test_bulk_confirm_dedupes_repeated_ids(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    pids = await _seed_proposed_persons(ledger, company_id, count=2)
    admin = pids[0]

    # Same id passed twice — orchestrator must not double-confirm.
    result = await write_actions.bulk_confirm_persons(
        ledger, company_id,
        person_ids=[pids[0], pids[1], pids[0]],
        confirmed_by=admin,
    )
    assert result["confirmed_count"] == 2
    assert result["person_ids"] == [str(pids[0]), str(pids[1])]
    assert len(result["entry_ids"]) == 4 * 2

    rows = await ledger.fetch(company_id)
    confirmed = [
        r["payload"]["args"]["person_id"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_person_confirmed"
    ]
    assert sorted(confirmed) == sorted(str(p) for p in pids)


@pytest.mark.asyncio
async def test_bulk_confirm_rejects_empty_input(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    with pytest.raises(ValueError, match="person_ids must not be empty"):
        await write_actions.bulk_confirm_persons(
            ledger, company_id, person_ids=[], confirmed_by=UUID(int=0),
        )
