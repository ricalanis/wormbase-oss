"""Identity-worm end-to-end: chat event → Reactivity → projection_persons."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_chat_presence import Install
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner
from wormbase_identity_tracker import (
    IdentityResolver,
    PersonHint,
    UnknownPlatformIdReactivity,
    wire_identity_for_install,
)


def _fake_member_lookup(platform: str, user: str) -> dict | None:
    """Stand-in for SlackChannelAdapter.users_info."""
    if platform != "slack":
        return None
    return {
        "name": f"User_{user}",
        "email": f"{user.lower()}@example.com",
    }


@pytest.mark.asyncio
async def test_e2e_unknown_platform_id_proposes_person() -> None:
    """Wire identity → write a chat_received entry → assert person proposed."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    # Wire the identity-worm.
    resolver = await wire_identity_for_install(
        install=install,
        member_lookup=_fake_member_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )
    assert isinstance(resolver, IdentityResolver)

    # Write a chat_received PEVR cycle for an unknown platform_user_id.
    # This mirrors what channel-adapter's writer does in production.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test inbound message",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "platform_user_id": "U_NEW_USER",
                "channel_id": "C123",
                "message_id": "msg-1",
                "text": "hello",
                "ts": datetime.now(UTC).isoformat(),
            },
            "result_ref": "msg-1",
        },
        verify_fn=lambda _e: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )

    # Dispatch entries through the registry, simulating ReactivityRunner.
    rows = await ledger.fetch(company)
    fired_ids: list[str] = []
    for r in rows:
        result = await registry.dispatch(r)
        fired_ids.extend(result)

    # The unknown_platform_id reactivity must have fired at least once.
    assert "unknown_platform_id" in fired_ids

    # Verify a person_proposed entry now exists.
    rows = await ledger.fetch(company)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_person_proposed"
    ]
    assert len(proposed) >= 1, "expected at least one emit_person_proposed entry"

    # The proposed Person carries the looked-up name + email.
    args = proposed[0]["payload"]["args"]
    assert args["platform"] == "slack"
    assert args["platform_user_id"] == "U_NEW_USER"
    assert args["name"] == "User_U_NEW_USER"
    assert args["email"] == "u_new_user@example.com"
    assert args["proposed_by"] == "worm"


@pytest.mark.asyncio
async def test_e2e_resolver_finds_proposed_person() -> None:
    """After the Reactivity fires, resolver.resolve_platform_id returns the Person."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    resolver = await wire_identity_for_install(
        install=install,
        member_lookup=_fake_member_lookup,
        reactivity_registry=registry,
        ledger=ledger,
        company_id=company,
    )

    # Drive a chat_received entry.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "platform_user_id": "U_E2E",
                "channel_id": "C123",
                "message_id": "msg-2",
                "text": "hi",
                "ts": datetime.now(UTC).isoformat(),
            },
            "result_ref": "msg-2",
        },
        verify_fn=lambda _e: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company)
    for r in rows:
        await registry.dispatch(r)

    # Now the resolver should find U_E2E.
    person = await resolver.resolve_platform_id(
        platform="slack", platform_user_id="U_E2E",
    )
    assert person is not None
    assert person.name == "User_U_E2E"
    assert person.platform == "slack"
    assert person.platform_user_id == "U_E2E"


@pytest.mark.asyncio
async def test_e2e_projection_persons_row_appears() -> None:
    """After fire, the projection-builder fold yields a `persons` row.

    Companion to ``test_e2e_unknown_platform_id_proposes_person`` (which
    asserts the LEDGER side) and ``test_e2e_resolver_finds_proposed_person``
    (which asserts the RESOLVER side). This test asserts the PROJECTION
    side: feeding the same entries through the canonical projection-builder
    fold produces a `projection_persons` row matching the proposed Person.

    NOTE on stack symmetry: in production the `ProjectionRunner` folds
    entries into Postgres `projection_persons`; we reuse the SAME
    `_apply_execute` fold used by `build_projections` so the test exercises
    the canonical projection logic verbatim. We don't go through
    `InMemoryLedger.replay()` because that helper's hand-rolled state dict
    omits the `persons` / `person_identities` keys (it predates identity-
    worm); going through `_apply_execute` directly is the same fold the
    DB-backed builder runs.
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

    # Drive a chat_received entry.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "channel_adapter",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "platform": "slack",
                "platform_user_id": "U_PROJ",
                "channel_id": "C123",
                "message_id": "msg-3",
                "text": "x",
                "ts": datetime.now(UTC).isoformat(),
            },
            "result_ref": "msg-3",
        },
        verify_fn=lambda _e: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company)
    for r in rows:
        await registry.dispatch(r)

    # Re-fetch (the fire() call appended new entries).
    rows = await ledger.fetch(company)

    # Apply the canonical projection-builder fold over every execute entry.
    # This mirrors what `build_projections` runs against Postgres in
    # production; the seed-state shape is taken verbatim from
    # `wormbase_ledger.projections.builder.build_projections`.
    from wormbase_ledger.projections.builder import _apply_execute

    state: dict = {
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
    for e in rows:
        if e["kind"] == "execute":
            _apply_execute(e, state)

    persons = list(state["persons"].values())
    matches = [
        p for p in persons
        if p.get("name") == "User_U_PROJ"
        and p.get("email") == "u_proj@example.com"
    ]
    assert len(matches) == 1, (
        f"expected one projection_persons row for U_PROJ; got {len(matches)}: "
        f"{persons}"
    )
    assert matches[0]["status"] == "proposed"
    assert matches[0]["proposed_by"] == "worm"

    # PersonIdentity row also appears, keyed on (tenant, platform, user_id).
    identities = list(state["person_identities"].values())
    id_matches = [
        i for i in identities
        if i.get("platform") == "slack"
        and i.get("platform_user_id") == "U_PROJ"
    ]
    assert len(id_matches) == 1, (
        f"expected one projection_person_identities row for slack/U_PROJ; "
        f"got {len(id_matches)}: {identities}"
    )
    assert id_matches[0]["person_id"] == matches[0]["person_id"]
