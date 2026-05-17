"""Identity projection replay tests (Block A1 of the production-dashboard PRD).

Each test drives the canonical write_primitive (`propose → execute → verify
→ resolve`) so the resulting `execute` envelope carries
`payload["tool"] == "emit_<kind>"`, then folds the ledger via
`build_projections` and asserts on the resulting `persons /
person_identities / installs` collections.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_person_proposed(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    name: str = "Bob",
    email: str | None = "bob@example.co",
    platform: str = "slack",
    platform_user_id: str = "U-bob",
    proposed_by: str = "worm",
    position: str | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "person_proposed",
                "ref_id": str(person_id),
                "reason": "auto-discovery",
                "proposed_by": proposed_by,
            },
            execute_fn=lambda: {
                "tool": "emit_person_proposed",
                "args": {
                    "person_id": str(person_id),
                    "tenant_id": str(company_id),
                    "name": name,
                    "email": email,
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "proposed_by": proposed_by,
                    "position": position,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_person_confirmed(
    engine: Any, *, company_id: UUID, person_id: UUID, confirmed_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "person_confirmed",
                "ref_id": str(person_id),
                "reason": "admin confirm",
                "proposed_by": str(confirmed_by),
            },
            execute_fn=lambda: {
                "tool": "emit_person_confirmed",
                "args": {
                    "person_id": str(person_id),
                    "confirmed_by": str(confirmed_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_identity_linked(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
    linked_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "identity_linked",
                "ref_id": str(person_id),
                "reason": "merge",
                "proposed_by": str(linked_by),
            },
            execute_fn=lambda: {
                "tool": "emit_identity_linked",
                "args": {
                    "person_id": str(person_id),
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "linked_by": str(linked_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_identity_unlinked(
    engine: Any,
    *,
    company_id: UUID,
    person_id: UUID,
    platform: str,
    platform_user_id: str,
    unlinked_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "identity_unlinked",
                "ref_id": str(person_id),
                "reason": "split",
                "proposed_by": str(unlinked_by),
            },
            execute_fn=lambda: {
                "tool": "emit_identity_unlinked",
                "args": {
                    "person_id": str(person_id),
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "unlinked_by": str(unlinked_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_install_completed(
    engine: Any,
    *,
    company_id: UUID,
    install_id: UUID,
    installer_person_id: UUID,
    platform: str = "slack",
    oauth_grant_ref: str = "kms://wormbase/install/abc",
    scopes: list[str] | None = None,
    bot_user_id: str = "B0X",
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "install_completed",
                "ref_id": str(install_id),
                "reason": "oauth",
                "proposed_by": str(installer_person_id),
            },
            execute_fn=lambda: {
                "tool": "emit_install_completed",
                "args": {
                    "install_id": str(install_id),
                    "tenant_id": str(company_id),
                    "platform": platform,
                    "installer_person_id": str(installer_person_id),
                    "oauth_grant_ref": oauth_grant_ref,
                    "scopes": scopes if scopes is not None else ["chat:write"],
                    "bot_user_id": bot_user_id,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_install_revoked(
    engine: Any, *, company_id: UUID, install_id: UUID, revoked_by: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "install_revoked",
                "ref_id": str(install_id),
                "reason": "user revoked",
                "proposed_by": str(revoked_by),
            },
            execute_fn=lambda: {
                "tool": "emit_install_revoked",
                "args": {
                    "install_id": str(install_id),
                    "revoked_by": str(revoked_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# Person lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_person_proposed_creates_person_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()

    await _emit_person_proposed(
        engine, company_id=company_id, person_id=person_id, name="Bob",
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.persons) == 1
    bob = proj.persons[0]
    assert bob["person_id"] == person_id
    assert bob["tenant_id"] == company_id
    assert bob["name"] == "Bob"
    assert bob["status"] == "proposed"
    assert bob["proposed_by"] == "worm"
    assert bob["confirmed_by"] is None


@pytest.mark.asyncio
async def test_person_proposed_creates_initial_person_identity(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()

    await _emit_person_proposed(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="slack",
        platform_user_id="U-bob",
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.person_identities) == 1
    pi = proj.person_identities[0]
    assert pi["person_id"] == person_id
    assert pi["tenant_id"] == company_id
    assert pi["platform"] == "slack"
    assert pi["platform_user_id"] == "U-bob"
    assert pi["display_name"] == "Bob"


@pytest.mark.asyncio
async def test_person_confirm_transitions_status(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    confirmer = uuid4()

    await _emit_person_proposed(
        engine, company_id=company_id, person_id=person_id, name="Bob",
    )
    await _emit_person_confirmed(
        engine, company_id=company_id, person_id=person_id, confirmed_by=confirmer,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.persons) == 1
    bob = proj.persons[0]
    assert bob["status"] == "active"
    assert bob["confirmed_by"] == confirmer


# ---------------------------------------------------------------------------
# Identity link / unlink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_linked_adds_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_person_proposed(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="slack",
        platform_user_id="U-bob",
    )
    # link a second platform identity to the same Person
    await _emit_identity_linked(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="discord",
        platform_user_id="bob#1234",
        linked_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    platforms = sorted(pi["platform"] for pi in proj.person_identities)
    assert platforms == ["discord", "slack"]
    discord_row = next(
        pi for pi in proj.person_identities if pi["platform"] == "discord"
    )
    assert discord_row["platform_user_id"] == "bob#1234"
    assert discord_row["person_id"] == person_id


@pytest.mark.asyncio
async def test_identity_unlinked_removes_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_person_proposed(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="slack",
        platform_user_id="U-bob",
    )
    await _emit_identity_linked(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="discord",
        platform_user_id="bob#1234",
        linked_by=admin,
    )
    await _emit_identity_unlinked(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="discord",
        platform_user_id="bob#1234",
        unlinked_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    platforms = [pi["platform"] for pi in proj.person_identities]
    assert platforms == ["slack"]


# ---------------------------------------------------------------------------
# Install lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_completed_writes_one_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.installs) == 1
    inst = proj.installs[0]
    assert inst["install_id"] == install_id
    assert inst["tenant_id"] == company_id
    assert inst["platform"] == "slack"
    assert inst["installer_person_id"] == installer
    assert inst["oauth_grant_ref"].startswith("kms://")
    assert inst["scopes"] == ["chat:write"]
    assert inst["status"] == "active"


@pytest.mark.asyncio
async def test_second_install_for_same_tenant_platform_updates_not_duplicates(
    test_database_url: str,
) -> None:
    """Re-installing for an existing (tenant, platform) replaces the row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id_1 = uuid4()
    install_id_2 = uuid4()
    installer_1 = uuid4()
    installer_2 = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id_1,
        installer_person_id=installer_1,
        oauth_grant_ref="kms://wormbase/install/v1",
    )
    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id_2,
        installer_person_id=installer_2,
        oauth_grant_ref="kms://wormbase/install/v2",
        scopes=["chat:write", "files:read"],
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.installs) == 1
    inst = proj.installs[0]
    # Latest install wins per (tenant, platform).
    assert inst["install_id"] == install_id_2
    assert inst["installer_person_id"] == installer_2
    assert inst["oauth_grant_ref"] == "kms://wormbase/install/v2"
    assert inst["scopes"] == ["chat:write", "files:read"]


@pytest.mark.asyncio
async def test_install_revoked_flips_status(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer,
    )
    await _emit_install_revoked(
        engine, company_id=company_id, install_id=install_id, revoked_by=installer,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.installs) == 1
    assert proj.installs[0]["status"] == "revoked"


# ---------------------------------------------------------------------------
# Determinism: the new state collections must be replay-stable.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_replay_is_deterministic(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    person_id = uuid4()

    await _emit_person_proposed(
        engine,
        company_id=company_id,
        person_id=person_id,
        platform="slack",
        platform_user_id="U-bob",
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert proj_a.persons == proj_b.persons
    # PersonIdentity rows must carry a deterministic identity_id (derived
    # from tenant/platform/platform_user_id, NOT a fresh uuid4).
    assert proj_a.person_identities == proj_b.person_identities
    assert proj_a.person_identities[0]["identity_id"] == (
        proj_b.person_identities[0]["identity_id"]
    )
