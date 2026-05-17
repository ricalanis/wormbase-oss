"""Unit tests for ``write_actions.merge_persons`` and ``split_person``.

A6 of ``docs/superpowers/plans/2026-04-26-production-dashboard.md``.

Each merge/split is a *sequence* of independent PEVR cycles. These tests
assert:
  - The current-identities-fold handles propose / link / unlink / re-link
    correctly (order matters; re-linking after unlink restores attachment).
  - Merge moves all of mergee's identities to keeper, archives the mergee,
    and writes the right audit trail.
  - Merge with overlap (same identity already on keeper) skips the
    duplicate link but still records the unlink on the mergee side.
  - Split extracts the requested identities, leaves the rest on the source.
  - Edge cases (keeper==mergee, empty identities_to_move) raise ValueError.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_core import write_actions
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


# ---------------------------------------------------------------------------
# Helpers — collect tools used in execute payloads
# ---------------------------------------------------------------------------


def _execute_tools(rows: list[dict]) -> list[str]:
    return [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]


def _execute_args_for_person(rows: list[dict], pid: UUID) -> list[dict]:
    out = []
    for r in rows:
        if r["kind"] != "execute":
            continue
        args = (r["payload"] or {}).get("args") or {}
        if args.get("person_id") == str(pid):
            out.append({"tool": r["payload"].get("tool"), **args})
    return out


# ---------------------------------------------------------------------------
# _current_identities_for_person — fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fold_handles_link_unlink_relink(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Order matters: link → unlink → re-link must resolve to ATTACHED."""
    pid, _ = await write_actions.propose_person(
        ledger, company_id,
        name="Bob", email="bob@x.co",
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    actor = uuid4()
    # link discord
    await write_actions.link_identity(
        ledger, company_id, person_id=pid,
        platform="discord", platform_user_id="bob#1234",
        linked_by=actor,
    )
    # unlink discord
    await write_actions.unlink_identity(
        ledger, company_id, person_id=pid,
        platform="discord", platform_user_id="bob#1234",
        unlinked_by=actor,
    )
    # re-link discord
    await write_actions.link_identity(
        ledger, company_id, person_id=pid,
        platform="discord", platform_user_id="bob#1234",
        linked_by=actor,
    )
    identities = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=pid,
    )
    assert ("slack", "U-bob") in identities
    assert ("discord", "bob#1234") in identities


@pytest.mark.asyncio
async def test_fold_skips_other_persons(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    p1, _ = await write_actions.propose_person(
        ledger, company_id, name="Alice", email=None,
        platform="slack", platform_user_id="U-alice",
        position=None, proposed_by="worm",
    )
    p2, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email=None,
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    p1_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=p1,
    )
    p2_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=p2,
    )
    assert p1_ids == [("slack", "U-alice")]
    assert p2_ids == [("slack", "U-bob")]


# ---------------------------------------------------------------------------
# merge_persons
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_two_persons_moves_identities_and_archives_mergee(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Standard merge: p2 (discord) merges into p1 (slack)."""
    admin = uuid4()
    p1, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email="bob@x.co",
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    p2, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob M", email="bob@x.co",
        platform="discord", platform_user_id="bob#1234",
        position=None, proposed_by="worm",
    )

    result = await write_actions.merge_persons(
        ledger, company_id, keeper_id=p1, mergee_id=p2, merged_by=admin,
    )

    assert result["keeper_id"] == str(p1)
    assert result["mergee_id"] == str(p2)
    assert result["identities_moved"] == 1
    # Each PEVR cycle writes 4 entries; we expect 1 unlink + 1 link + 1 archive
    # = 3 cycles = 12 entries listed in entry_ids.
    assert len(result["entry_ids"]) == 12

    # Keeper now owns both identities.
    keeper_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=p1,
    )
    assert set(keeper_ids) == {("slack", "U-bob"), ("discord", "bob#1234")}

    # Mergee has no identities.
    mergee_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=p2,
    )
    assert mergee_ids == []

    # Audit trail: full execute-tool sequence under the mergee includes
    # propose + unlink + archive; under keeper, propose + link.
    rows = await ledger.fetch(company_id)
    tools = _execute_tools(rows)
    assert tools.count("emit_identity_unlinked") == 1
    assert tools.count("emit_identity_linked") == 1
    assert tools.count("emit_person_archived") == 1

    # Hash chain still valid.
    ok, broken = verify_chain(rows)
    assert ok and broken is None


@pytest.mark.asyncio
async def test_merge_with_overlap_skips_double_link(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """If both Persons share an identity (e.g. same Slack id),
    the duplicate is just unlinked from mergee — no double-link on keeper."""
    admin = uuid4()
    p1, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email=None,
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    p2, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email=None,
        platform="slack", platform_user_id="U-bob-dup",  # different
        position=None, proposed_by="worm",
    )
    # Manually link the SAME identity to both persons (an unusual but
    # exercisable state — could happen across discovery races).
    await write_actions.link_identity(
        ledger, company_id, person_id=p1,
        platform="discord", platform_user_id="shared#1",
        linked_by=admin,
    )
    await write_actions.link_identity(
        ledger, company_id, person_id=p2,
        platform="discord", platform_user_id="shared#1",
        linked_by=admin,
    )

    result = await write_actions.merge_persons(
        ledger, company_id, keeper_id=p1, mergee_id=p2, merged_by=admin,
    )

    # Mergee had 2 identities (U-bob-dup + shared#1); shared#1 was already
    # on the keeper, so we move 1 (U-bob-dup) and skip the link for shared#1.
    assert result["identities_moved"] == 1

    keeper_ids = set(
        await write_actions._current_identities_for_person(
            ledger, company_id, person_id=p1,
        )
    )
    assert ("slack", "U-bob") in keeper_ids
    assert ("slack", "U-bob-dup") in keeper_ids
    assert ("discord", "shared#1") in keeper_ids
    # Crucially: shared#1 is present once, not twice — fold is idempotent.

    # The mergee no longer holds shared#1 either (we unlinked it).
    mergee_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=p2,
    )
    assert mergee_ids == []

    # Verify exact audit shape: 2 unlinks (one per mergee identity) +
    # 1 link (the non-overlapping one) + 1 archive.
    rows = await ledger.fetch(company_id)
    tools = _execute_tools(rows)
    assert tools.count("emit_identity_unlinked") == 2
    # Only one new link was written for the merge phase (plus the two
    # initial setup links and 2 propose entries).
    assert tools.count("emit_identity_linked") == 3  # 2 setup + 1 from merge
    assert tools.count("emit_person_archived") == 1


@pytest.mark.asyncio
async def test_merge_keeper_equals_mergee_raises(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    p1, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email=None,
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    with pytest.raises(ValueError, match="must differ"):
        await write_actions.merge_persons(
            ledger, company_id, keeper_id=p1, mergee_id=p1, merged_by=uuid4(),
        )


# ---------------------------------------------------------------------------
# split_person
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_extracts_subset_of_identities(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Source has 3 identities; split extracts 2; source keeps 1."""
    admin = uuid4()
    src, _ = await write_actions.propose_person(
        ledger, company_id, name="Alice + Bob", email=None,
        platform="slack", platform_user_id="U-alice",
        position=None, proposed_by="worm",
    )
    await write_actions.link_identity(
        ledger, company_id, person_id=src,
        platform="discord", platform_user_id="bob#1234",
        linked_by=admin,
    )
    await write_actions.link_identity(
        ledger, company_id, person_id=src,
        platform="teams", platform_user_id="bob@x.co",
        linked_by=admin,
    )

    result = await write_actions.split_person(
        ledger, company_id,
        source_person_id=src,
        new_person_name="Bob",
        new_person_email="bob@x.co",
        new_person_position="engineer",
        identities_to_move=[
            ("discord", "bob#1234"),
            ("teams", "bob@x.co"),
        ],
        split_by=admin,
    )

    assert result["source_person_id"] == str(src)
    new_pid = UUID(result["new_person_id"])
    assert result["identities_moved"] == 2

    # Source keeps slack only.
    src_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=src,
    )
    assert src_ids == [("slack", "U-alice")]

    # New person has discord + teams.
    new_ids = set(
        await write_actions._current_identities_for_person(
            ledger, company_id, person_id=new_pid,
        )
    )
    assert new_ids == {("discord", "bob#1234"), ("teams", "bob@x.co")}

    rows = await ledger.fetch(company_id)
    ok, broken = verify_chain(rows)
    assert ok and broken is None


@pytest.mark.asyncio
async def test_split_with_dict_form_identities(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Identities supplied as dicts (HTTP-shaped) work too."""
    admin = uuid4()
    src, _ = await write_actions.propose_person(
        ledger, company_id, name="Source", email=None,
        platform="slack", platform_user_id="U-src",
        position=None, proposed_by="worm",
    )
    await write_actions.link_identity(
        ledger, company_id, person_id=src,
        platform="discord", platform_user_id="src#1",
        linked_by=admin,
    )

    result = await write_actions.split_person(
        ledger, company_id,
        source_person_id=src,
        new_person_name="Other",
        new_person_email=None,
        new_person_position=None,
        identities_to_move=[
            {"platform": "discord", "platform_user_id": "src#1"},
        ],
        split_by=admin,
    )
    assert result["identities_moved"] == 1


@pytest.mark.asyncio
async def test_split_all_identities_leaves_source_empty(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    """Edge case: split moves ALL identities — source ends up identity-less.

    This is allowed; the admin is doing it intentionally. The Person row
    still exists; an admin can archive it as a follow-up.
    """
    admin = uuid4()
    src, _ = await write_actions.propose_person(
        ledger, company_id, name="Misattributed", email=None,
        platform="slack", platform_user_id="U-x",
        position=None, proposed_by="worm",
    )
    await write_actions.link_identity(
        ledger, company_id, person_id=src,
        platform="discord", platform_user_id="x#1",
        linked_by=admin,
    )

    await write_actions.split_person(
        ledger, company_id,
        source_person_id=src,
        new_person_name="Recovered",
        new_person_email=None,
        new_person_position=None,
        identities_to_move=[
            ("slack", "U-x"),
            ("discord", "x#1"),
        ],
        split_by=admin,
    )
    src_ids = await write_actions._current_identities_for_person(
        ledger, company_id, person_id=src,
    )
    assert src_ids == []


@pytest.mark.asyncio
async def test_split_empty_identities_raises(
    ledger: InMemoryLedger, company_id: UUID,
) -> None:
    src, _ = await write_actions.propose_person(
        ledger, company_id, name="Bob", email=None,
        platform="slack", platform_user_id="U-bob",
        position=None, proposed_by="worm",
    )
    with pytest.raises(ValueError, match="must not be empty"):
        await write_actions.split_person(
            ledger, company_id,
            source_person_id=src,
            new_person_name="Other",
            new_person_email=None,
            new_person_position=None,
            identities_to_move=[],
            split_by=uuid4(),
        )
