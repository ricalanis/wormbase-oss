"""Unit tests for ``write_actions.complete_install`` — the Tier 1
post-OAuth orchestrator.

Verifies the orchestrator writes the full chain (propose installer
Person → confirm → grant tenancy.installer + tenancy.admin →
emit_install_completed) as five PEVR cycles in order. Runs against
``InMemoryLedger`` so the test stays docker-free.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


TENANT_SLUG = "baseworm"


@pytest.mark.asyncio
async def test_complete_install_writes_full_chain() -> None:
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)

    result = await write_actions.complete_install(
        ledger,
        company_id,
        platform="slack",
        installer_email="carol@x.co",
        installer_name="Carol Reyes",
        installer_avatar_url=None,
        platform_user_id="UCAROL",
        oauth_grant_ref="vault://local-dev/abc123",
        scopes=["channels:read", "chat:write"],
        bot_user_id="UBOT",
    )

    # Result envelope is well-formed.
    assert UUID(result["install_id"])
    assert UUID(result["installer_person_id"])
    # Block I (production-dashboard PRD §17): complete_install now also
    # auto-provisions the default local lake (4 PEVR cycles, 16 entries)
    # after writing emit_install_completed. Total: 5 install + 4 lake =
    # 9 PEVR cycles × 4 entries = 36 entries.
    assert UUID(result["local_lake_source_id"])
    assert len(result["entry_ids"]) == 36

    # Ledger fold: assert kinds + tools in canonical order.
    rows = await ledger.fetch(company_id)
    assert len(rows) == 36

    # Each PEVR cycle is exactly 4 entries: propose / execute / verify / resolve.
    for cycle_start in range(0, 36, 4):
        kinds = [rows[cycle_start + i]["kind"] for i in range(4)]
        assert kinds == ["propose", "execute", "verify", "resolve"]

    # Tool sequence at each execute step:
    tools = [rows[cycle_start + 1]["payload"]["tool"] for cycle_start in range(0, 36, 4)]
    assert tools == [
        "emit_person_proposed",
        "emit_person_confirmed",
        "emit_role_assigned",  # tenancy.installer
        "emit_role_assigned",  # tenancy.admin
        "emit_install_completed",
        # Block I: default local lake auto-provisioned at install.
        "emit_source_proposed",
        "emit_source_confirmed",
        "emit_source_connected",
        "emit_source_profiled",
    ]

    # Hash chain is unbroken across all 36 entries.
    ok, broken_at = verify_chain(rows)
    assert ok and broken_at is None

    # Inspect tenancy roles granted.
    role_grants = [
        rows[i]["payload"]["args"]
        for i in range(36)
        if rows[i]["kind"] == "execute"
        and rows[i]["payload"]["tool"] == "emit_role_assigned"
    ]
    roles_granted = [g["role"] for g in role_grants]
    assert roles_granted == ["installer", "admin"]
    # Both grants are self-grants — granted_by == person_id.
    person_id = result["installer_person_id"]
    assert all(g["granted_by"] == person_id for g in role_grants)

    # The install_completed payload carries the right shape.
    # Cycle 5 (rows 16-19): execute is at offset 1 → row 17.
    install_args = rows[17]["payload"]["args"]
    assert install_args["install_id"] == result["install_id"]
    assert install_args["platform"] == "slack"
    assert install_args["installer_person_id"] == person_id
    assert install_args["oauth_grant_ref"] == "vault://local-dev/abc123"
    assert install_args["bot_user_id"] == "UBOT"
    assert install_args["scopes"] == ["channels:read", "chat:write"]

    # The local-lake source_proposed entry references the installer.
    # Cycle 6 (rows 20-23): execute at offset 1 → row 21.
    lake_propose_args = rows[21]["payload"]["args"]
    assert lake_propose_args["uri"] == f"local-lake://{company_id}"
    assert lake_propose_args["added_via_flow"] == "provisioned_at_install"
    assert lake_propose_args["added_by_person"] == person_id


@pytest.mark.asyncio
async def test_complete_install_rejects_raw_token() -> None:
    """oauth_grant_ref MUST start with kms:// or vault://. A raw token
    leaks credentials into the ledger; the payload validator rejects it
    and the orchestrator surfaces that as a ValueError."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)

    with pytest.raises(ValueError):
        await write_actions.complete_install(
            ledger,
            company_id,
            platform="slack",
            installer_email="carol@x.co",
            installer_name="Carol Reyes",
            installer_avatar_url=None,
            platform_user_id="UCAROL",
            oauth_grant_ref="xoxb-raw-bearer-token",  # rejected
            scopes=[],
            bot_user_id="UBOT",
        )


@pytest.mark.asyncio
async def test_complete_install_rejects_dev_prefix() -> None:
    """The deleted ``dev://`` prefix must never be accepted again.

    Regression guard: D7's previous shape synthesized fake grants like
    ``dev://wormbase/{slug}/...``. The Pydantic validator rejects
    anything that isn't ``kms://`` or ``vault://``; we exercise that
    path so a future agent cannot reintroduce the dev shortcut.
    """
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)

    with pytest.raises(ValueError):
        await write_actions.complete_install(
            ledger,
            company_id,
            platform="slack",
            installer_email="carol@x.co",
            installer_name="Carol Reyes",
            installer_avatar_url=None,
            platform_user_id="UCAROL",
            oauth_grant_ref="dev://wormbase/baseworm/slack/abc",
            scopes=[],
            bot_user_id="UBOT",
        )


@pytest.mark.asyncio
async def test_complete_install_requires_installer_email() -> None:
    """Empty installer_email is a configuration error — surface it."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)

    with pytest.raises(ValueError):
        await write_actions.complete_install(
            ledger,
            company_id,
            platform="slack",
            installer_email="",
            installer_name="Carol",
            installer_avatar_url=None,
            platform_user_id="UCAROL",
            oauth_grant_ref="vault://local/abc",
            scopes=[],
            bot_user_id="UBOT",
        )
