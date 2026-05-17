"""Setup-projection replay tests (Block G of the production-dashboard PRD §17).

Three new tools — emit_setup_mode_chosen / emit_setup_completed /
emit_setup_step_advanced — fold into:

* ``projection_installs.setup_mode`` (mirror of the latest mode_chosen)
* ``projection_installs.setup_completed_at`` (final timestamp)
* ``projection_setup_progress`` table (per-tenant cursor through bot YAML)
"""

from __future__ import annotations

from datetime import UTC, datetime
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


async def _emit_install_completed(
    engine: Any,
    *,
    company_id: UUID,
    install_id: UUID,
    installer_person_id: UUID,
    platform: str = "slack",
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
                    "oauth_grant_ref": "kms://wormbase/install/abc",
                    "scopes": ["chat:write"],
                    "bot_user_id": "B0X",
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_setup_mode_chosen(
    engine: Any,
    *,
    company_id: UUID,
    mode: str,
    chosen_by_person_id: UUID,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "setup_mode_chosen",
                "ref_id": str(company_id),
                "reason": "T2 fork",
                "proposed_by": str(chosen_by_person_id),
            },
            execute_fn=lambda: {
                "tool": "emit_setup_mode_chosen",
                "args": {
                    "tenant_id": str(company_id),
                    "mode": mode,
                    "chosen_by_person_id": str(chosen_by_person_id),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_setup_completed(
    engine: Any,
    *,
    company_id: UUID,
    completed_at: datetime,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "setup_completed",
                "ref_id": str(company_id),
                "reason": "wizard final form / bot done step",
                "proposed_by": "wizard-or-bot",
            },
            execute_fn=lambda: {
                "tool": "emit_setup_completed",
                "args": {
                    "tenant_id": str(company_id),
                    "completed_at": completed_at.isoformat(),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_setup_step_advanced(
    engine: Any,
    *,
    company_id: UUID,
    step_id: str,
    advanced_by_person_id: UUID | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "setup_step_advanced",
                "ref_id": str(company_id),
                "reason": f"installer answered {step_id}",
                "proposed_by": str(advanced_by_person_id or "worm"),
            },
            execute_fn=lambda: {
                "tool": "emit_setup_step_advanced",
                "args": {
                    "tenant_id": str(company_id),
                    "step_id": step_id,
                    "advanced_by_person_id": (
                        str(advanced_by_person_id)
                        if advanced_by_person_id is not None
                        else None
                    ),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# setup_mode_chosen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_mode_defaults_null_on_install(test_database_url: str) -> None:
    """A fresh install has setup_mode=None until the user picks in T2."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer_id = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.installs) == 1
    inst = proj.installs[0]
    assert inst["setup_mode"] is None
    assert inst["setup_completed_at"] is None


@pytest.mark.asyncio
async def test_setup_mode_chosen_stamps_install(test_database_url: str) -> None:
    """Choosing 'wizard' stamps the install row's setup_mode."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer_id = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer_id,
    )
    await _emit_setup_mode_chosen(
        engine,
        company_id=company_id,
        mode="wizard",
        chosen_by_person_id=installer_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.installs) == 1
    inst = proj.installs[0]
    assert inst["setup_mode"] == "wizard"
    assert inst["setup_completed_at"] is None


@pytest.mark.asyncio
async def test_setup_mode_can_switch_wizard_to_bot(test_database_url: str) -> None:
    """G6: admins can switch mode in /settings before completion."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer_id = uuid4()

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer_id,
    )
    await _emit_setup_mode_chosen(
        engine,
        company_id=company_id,
        mode="wizard",
        chosen_by_person_id=installer_id,
    )
    await _emit_setup_mode_chosen(
        engine,
        company_id=company_id,
        mode="bot",
        chosen_by_person_id=installer_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    inst = proj.installs[0]
    assert inst["setup_mode"] == "bot"


# ---------------------------------------------------------------------------
# setup_completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_completed_stamps_install(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    install_id = uuid4()
    installer_id = uuid4()
    completed = datetime(2026, 4, 26, 14, 30, 0, tzinfo=UTC)

    await _emit_install_completed(
        engine,
        company_id=company_id,
        install_id=install_id,
        installer_person_id=installer_id,
    )
    await _emit_setup_mode_chosen(
        engine,
        company_id=company_id,
        mode="wizard",
        chosen_by_person_id=installer_id,
    )
    await _emit_setup_completed(
        engine, company_id=company_id, completed_at=completed,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    inst = proj.installs[0]
    assert inst["setup_completed_at"] is not None


# ---------------------------------------------------------------------------
# setup_step_advanced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_step_advanced_creates_progress_row(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    installer_id = uuid4()

    await _emit_setup_step_advanced(
        engine,
        company_id=company_id,
        step_id="domain_pack",
        advanced_by_person_id=installer_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.setup_progress) == 1
    row = proj.setup_progress[0]
    assert row["tenant_id"] == company_id
    assert row["current_step"] == "domain_pack"
    assert row["steps_completed"] == ["domain_pack"]
    assert row["last_advance_seq"] is not None
    assert row["last_advance_ts"] is not None


@pytest.mark.asyncio
async def test_setup_step_advanced_appends_in_order(
    test_database_url: str,
) -> None:
    """Multiple advances grow steps_completed in advance order."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    installer_id = uuid4()

    for step in ("domain_pack", "classification_default", "invite_admins"):
        await _emit_setup_step_advanced(
            engine,
            company_id=company_id,
            step_id=step,
            advanced_by_person_id=installer_id,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.setup_progress) == 1
    row = proj.setup_progress[0]
    assert row["current_step"] == "invite_admins"
    assert row["steps_completed"] == [
        "domain_pack",
        "classification_default",
        "invite_admins",
    ]


@pytest.mark.asyncio
async def test_setup_step_advanced_no_double_count(
    test_database_url: str,
) -> None:
    """Re-advancing the same step doesn't duplicate it in steps_completed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    await _emit_setup_step_advanced(
        engine, company_id=company_id, step_id="domain_pack",
    )
    await _emit_setup_step_advanced(
        engine, company_id=company_id, step_id="domain_pack",
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    row = proj.setup_progress[0]
    assert row["steps_completed"] == ["domain_pack"]


@pytest.mark.asyncio
async def test_setup_progress_is_per_tenant(test_database_url: str) -> None:
    """Two tenants advance independently."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()

    await _emit_setup_step_advanced(
        engine, company_id=tenant_a, step_id="domain_pack",
    )
    await _emit_setup_step_advanced(
        engine, company_id=tenant_b, step_id="first_kpi",
    )

    async with session_scope(engine) as tenant_a_session:
        proj_a = await build_projections(tenant_a_session, tenant_a)
    async with session_scope(engine) as tenant_b_session:
        proj_b = await build_projections(tenant_b_session, tenant_b)

    assert len(proj_a.setup_progress) == 1
    assert proj_a.setup_progress[0]["current_step"] == "domain_pack"

    assert len(proj_b.setup_progress) == 1
    assert proj_b.setup_progress[0]["current_step"] == "first_kpi"
