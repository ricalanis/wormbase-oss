"""Identity greenfield e2e — Wave B.5 G.7 sign-off test.

Closes the Wave B.5 loop on the two new identity-tracker Reactivities by
exercising both end-to-end through the production wire path:

  * ``PositionInferenceReactivity`` (G.4) — chat events with role-
    signaling tokens cause an ``emit_position_proposed`` PEVR cycle to
    land; the projection-builder fold materializes the proposed position
    onto ``projection_persons.position``.
  * ``ResourceOwnershipReactivity`` (G.5) — chat events that mention a
    resource UUID by the same Person cause an
    ``emit_resource_role_proposed`` PEVR cycle to land; the projection
    fold writes a ``projection_roles`` row with ``facet='resource'``.

The test wires the worm via ``wire_identity_for_install`` (the same path
``apps/worm-core/src/wormbase_core/cli.py`` calls at boot), seeds
``chat_received`` envelopes through the canonical ``ledger.write`` PEVR
shape (the same shape ``channel-adapter`` uses in production), drives
the registry once, and asserts both the LEDGER side (PEVR cycle landed,
payload validated) and the PROJECTION side (projection-builder fold
materializes the expected projection rows).

No flow-bypass shortcuts: every entry lands through the same
``ledger.write`` primitive ``channel-adapter`` uses. No
``_patch_registry_extras`` bridges (Block C eliminated those). The only
difference between this test and a live ``channel-adapter`` flow is the
input source — here ``chat_received`` envelopes are constructed directly
instead of normalized from raw Slack events.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from wormbase_chat_presence import Install
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ChatReceivedPayload, PersonProposedPayload
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner
from wormbase_identity_tracker import wire_identity_for_install


def _fake_member_lookup(platform: str, user: str) -> dict | None:
    """Stand-in for SlackChannelAdapter.users_info — unused by the
    greenfield Reactivities (they read directly from the ledger) but
    required by ``UnknownPlatformIdReactivity`` which the same
    ``wire_identity_for_install`` boot path also registers.
    """
    if platform != "slack":
        return None
    return {
        "name": f"User_{user}",
        "email": f"{user.lower()}@example.com",
    }


async def _seed_person_proposed(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    person_id: UUID,
    name: str,
) -> None:
    """Seed a ``emit_person_proposed`` PEVR for ``person_id`` so the
    projection fold has a target row for the position write.

    Same shape ``UnknownPlatformIdReactivity`` would produce in the live
    wire path; we seed it directly here to keep the focus on G.4 / G.5.
    """
    payload = PersonProposedPayload(
        person_id=person_id,
        tenant_id=company_id,
        name=name,
        email=f"{name.lower()}@example.com",
        platform="slack",
        platform_user_id=f"U_{name.upper()}",
        proposed_by="worm",
    )
    args = payload.model_dump(mode="json")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "person_proposed",
            "ref_id": str(person_id),
            "reason": "greenfield e2e seed",
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


async def _seed_chat_received(
    ledger: InMemoryLedger,
    company_id: UUID,
    *,
    sender_person: UUID,
    text: str,
    channel_id: str = "C_GREEN",
) -> str:
    """Seed a ``channel_adapter.emit_chat_received`` envelope.

    Same Pydantic-validated shape ``channel-adapter`` writes in the live
    wire path.
    """
    payload = ChatReceivedPayload(
        channel_id=channel_id,
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
            "reason": "e2e inbound",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": args["message_id"],
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    return args["message_id"]


def _filter_executes(rows: list[dict], tool: str) -> list[dict]:
    """Return execute entries whose payload.tool matches ``tool``."""
    return [
        r for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool") == tool
    ]


def _initial_projection_state() -> dict:
    """Mirror of ``wormbase_ledger.projections.builder.build_projections``
    seed state. Kept inline so this test stays decoupled from any private
    helper inside the builder module — if a new key is added to the
    builder seed, this test will fail loudly when it tries to fold an
    entry that touches it.
    """
    return {
        "sources": {},
        "memory": [],
        "kpi_nodes": {},
        "persons": {},
        "person_identities": {},
        "installs": {},
        "roles": {},
        "data_products": {},
        "data_product_runs": {},
        "data_product_consumption": {},
        "notebooks": {},
        "notebook_runs": {},
        "setup_progress": {},
        "mcp_calls": {},
        "chat_count": 0,
        "resolve_count": 0,
    }


@pytest.mark.asyncio
async def test_e2e_greenfield_position_proposed_lands_and_projects() -> None:
    """5 data-engineer-signaling chats → emit_position_proposed lands.

    Drives:
      * wire_identity_for_install (registers all 3 Reactivities)
      * 5 chat_received events from one person with DE patterns
      * registry.dispatch on each (production wire path)

    Asserts:
      * emit_position_proposed entry lands with confidence ≥ 0.5
      * The PEVR cycle is complete (propose → execute → verify → resolve)
      * The verify check passes Pydantic payload validation
      * The projection-builder fold materializes
        projection_persons.position == "data_engineer"
    """
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    await wire_identity_for_install(
        install=install,
        member_lookup=_fake_member_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )

    # All three Reactivities are registered (G.6).
    registered = {r.id for r in registry.list()}
    assert registered == {
        "unknown_platform_id",
        "position_inference",
        "resource_ownership",
    }

    # Seed the Person row so the projection fold has a target.
    pid = uuid4()
    await _seed_person_proposed(ledger, company, person_id=pid, name="Dee")

    # Drive 5 chat_received events with data-engineer signal tokens.
    # The DE position has 5 patterns: "why is", "when did this break",
    # "what changed", "schema", "query cost".
    chat_texts = [
        "why is the bronze→silver pipeline lagging today?",
        "schema drift on the orders table — what changed?",
        "our query cost on snowflake spiked 3x overnight",
        "when did this break? was it the friday deploy?",
        "anyone else seeing the schema mismatch in silver?",
    ]
    for text in chat_texts:
        await _seed_chat_received(
            ledger, company, sender_person=pid, text=text,
        )

    # Drive the registry (production wire path: dispatch each entry).
    rows = await ledger.fetch(company)
    for r in rows:
        await registry.dispatch(r)

    # Assert: emit_position_proposed entry lands.
    rows = await ledger.fetch(company)
    proposals = _filter_executes(rows, "emit_position_proposed")
    assert len(proposals) == 1, (
        f"expected exactly 1 emit_position_proposed; got {len(proposals)}: "
        f"{[p['payload']['args'] for p in proposals]}"
    )
    args = proposals[0]["payload"]["args"]
    assert args["person_id"] == str(pid)
    assert args["position"] == "data_engineer"
    assert args["confidence"] >= 0.5
    assert args["signals"], "signals tuple should be non-empty"

    # Assert: full PEVR cycle landed for this propose.
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx = next(
        i for i, r in enumerate(rows_sorted)
        if r.get("kind") == "propose"
        and (r.get("payload") or {}).get("target_kind") == "position_proposed"
        and (r.get("payload") or {}).get("ref_id") == str(pid)
    )
    pevr_kinds = [
        r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]
    ]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"]
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == "emit_position_proposed_payload_valid"
    assert checks[0]["ok"] is True
    resolve_row = rows_sorted[propose_idx + 3]
    assert resolve_row["payload"].get("outcome") == "keep"

    # Assert: projection fold yields persons[pid].position == "data_engineer".
    from wormbase_ledger.projections.builder import _apply_execute

    state = _initial_projection_state()
    for e in rows_sorted:
        if e["kind"] == "execute":
            _apply_execute(e, state)

    person_row = state["persons"].get(str(pid))
    assert person_row is not None, (
        f"expected projection_persons row for {pid}; got keys "
        f"{list(state['persons'].keys())}"
    )
    assert person_row.get("position") == "data_engineer", (
        f"expected projection_persons.position='data_engineer'; got "
        f"{person_row.get('position')!r}"
    )


@pytest.mark.asyncio
async def test_e2e_greenfield_resource_role_proposed_lands_and_projects() -> None:
    """5 chats mentioning a resource UUID → emit_resource_role_proposed lands.

    Drives:
      * wire_identity_for_install (all 3 Reactivities)
      * 5 chat_received events from one person, each mentioning the same
        resource UUID (above the 0.5 threshold: 5/4.0 → capped at 1.0)
      * registry.dispatch on each

    Asserts:
      * emit_resource_role_proposed entry lands with confidence ≥ 0.5
      * Full PEVR cycle complete with payload-validated verify
      * Projection fold writes a roles row with facet='resource' and
        role='maintainer' for (person_id, resource_id)
    """
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    await wire_identity_for_install(
        install=install,
        member_lookup=_fake_member_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )

    pid = uuid4()
    resource_id = uuid4()  # canonical 8-4-4-4-12 UUID — the regex matches
    await _seed_person_proposed(ledger, company, person_id=pid, name="Bob")

    # Drive 5 chat events, each mentioning the resource UUID. The
    # ResourceOwnershipReactivity counts each as a chat_mention signal;
    # 5 mentions / 4.0 = capped at 1.0 confidence (≥ 0.5 threshold).
    for i in range(5):
        await _seed_chat_received(
            ledger, company, sender_person=pid,
            text=f"working on resource {resource_id} again today (#{i})",
        )

    rows = await ledger.fetch(company)
    for r in rows:
        await registry.dispatch(r)

    # Assert: emit_resource_role_proposed entry lands.
    rows = await ledger.fetch(company)
    proposals = _filter_executes(rows, "emit_resource_role_proposed")
    assert len(proposals) == 1, (
        f"expected exactly 1 emit_resource_role_proposed; got "
        f"{len(proposals)}: {[p['payload']['args'] for p in proposals]}"
    )
    args = proposals[0]["payload"]["args"]
    assert args["person_id"] == str(pid)
    assert args["resource_id"] == str(resource_id)
    assert args["role"] == "maintainer"
    assert args["confidence"] >= 0.5
    assert "chat_mention" in args["signals"]

    # Assert: full PEVR cycle landed.
    rows_sorted = sorted(rows, key=lambda r: r["seq"])
    propose_idx = next(
        i for i, r in enumerate(rows_sorted)
        if r.get("kind") == "propose"
        and (r.get("payload") or {}).get("target_kind") == "resource_role_proposed"
        and (r.get("payload") or {}).get("ref_id") == str(resource_id)
    )
    pevr_kinds = [
        r["kind"] for r in rows_sorted[propose_idx:propose_idx + 4]
    ]
    assert pevr_kinds == ["propose", "execute", "verify", "resolve"]
    verify_row = rows_sorted[propose_idx + 2]
    checks = verify_row["payload"].get("checks") or []
    assert checks and checks[0]["name"] == (
        "emit_resource_role_proposed_payload_valid"
    )
    assert checks[0]["ok"] is True
    resolve_row = rows_sorted[propose_idx + 3]
    assert resolve_row["payload"].get("outcome") == "keep"

    # Assert: projection fold writes a projection_roles row with
    # facet='resource' for the (person_id, resource_id) pair.
    from wormbase_ledger.projections.builder import _apply_execute

    state = _initial_projection_state()
    for e in rows_sorted:
        if e["kind"] == "execute":
            _apply_execute(e, state)

    matching = [
        row for row in state["roles"].values()
        if row.get("facet") == "resource"
        and str(row.get("person_id")) == str(pid)
        and str(row.get("scope_id")) == str(resource_id)
    ]
    assert len(matching) == 1, (
        f"expected one projection_roles row with facet='resource' for "
        f"({pid}, {resource_id}); got {len(matching)}: "
        f"{list(state['roles'].values())}"
    )
    assert matching[0]["role"] == "maintainer"


@pytest.mark.asyncio
async def test_e2e_greenfield_both_reactivities_fire_in_one_session() -> None:
    """Both greenfield Reactivities can fire on the same wire stream.

    The position-inference patterns (data-engineer tokens) and resource-
    UUID mentions are independent signals; a single chat history can
    contain both, and one session of dispatch should land BOTH proposal
    kinds. This protects against accidental coupling between the two
    Reactivities (e.g. one shadowing the other's predicate).
    """
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    await wire_identity_for_install(
        install=install,
        member_lookup=_fake_member_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )

    pid = uuid4()
    resource_id = uuid4()
    await _seed_person_proposed(ledger, company, person_id=pid, name="Carol")

    # Mix: 3 DE-pattern chats + 2 resource-mention chats. The DE chats
    # also happen to NOT mention the resource UUID (it would inflate
    # signal counts but not violate the contract).
    de_texts = [
        "why is the pipeline slow today?",
        "schema drift again on bronze",
        "what changed in the silver build?",
    ]
    for text in de_texts:
        await _seed_chat_received(
            ledger, company, sender_person=pid, text=text,
        )
    for i in range(2):
        await _seed_chat_received(
            ledger, company, sender_person=pid,
            text=f"opening resource {resource_id} (run {i})",
        )

    rows = await ledger.fetch(company)
    for r in rows:
        await registry.dispatch(r)

    rows = await ledger.fetch(company)
    pos_proposals = _filter_executes(rows, "emit_position_proposed")
    role_proposals = _filter_executes(rows, "emit_resource_role_proposed")

    assert len(pos_proposals) == 1
    assert pos_proposals[0]["payload"]["args"]["position"] == "data_engineer"

    assert len(role_proposals) == 1
    assert (
        role_proposals[0]["payload"]["args"]["resource_id"]
        == str(resource_id)
    )
    assert role_proposals[0]["payload"]["args"]["role"] == "maintainer"
