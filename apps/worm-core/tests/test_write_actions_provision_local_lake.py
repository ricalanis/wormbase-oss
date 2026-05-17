"""Tests for ``write_actions.provision_local_lake`` — the auto-provisioning
orchestrator that gives every tenant a default lake at install.

Two layers:

* ``test_provision_local_lake_*`` — the orchestrator in isolation, with
  a pre-existing installer Person uuid. Verifies it writes four PEVR
  cycles (16 entries: propose / execute / verify / resolve × 4) for the
  canonical source-lifecycle (proposed → confirmed → connected →
  profiled).

* ``test_complete_install_provisions_local_lake`` — the
  ``complete_install`` end-to-end now auto-calls
  ``provision_local_lake`` after writing ``emit_install_completed``.
  The full chain becomes 9 PEVR cycles × 4 entries = 36 entries.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.hash_chain import verify_chain


TENANT_SLUG = "baseworm"


# ---------------------------------------------------------------------------
# provision_local_lake in isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_local_lake_writes_four_pevr_cycles() -> None:
    """The orchestrator writes the canonical 4-stage source lifecycle as
    four PEVR cycles totalling 16 entries."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    result = await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )

    assert UUID(result["source_id"])
    assert len(result["entry_ids"]) == 16

    rows = await ledger.fetch(company_id)
    assert len(rows) == 16

    # Each PEVR cycle is exactly 4 entries: propose / execute / verify / resolve.
    for cycle_start in range(0, 16, 4):
        kinds = [rows[cycle_start + i]["kind"] for i in range(4)]
        assert kinds == ["propose", "execute", "verify", "resolve"]

    # Tool sequence at each execute step matches the source lifecycle.
    tools = [
        rows[cycle_start + 1]["payload"]["tool"]
        for cycle_start in range(0, 16, 4)
    ]
    assert tools == [
        "emit_source_proposed",
        "emit_source_confirmed",
        "emit_source_connected",
        "emit_source_profiled",
    ]

    ok, broken_at = verify_chain(rows)
    assert ok and broken_at is None


@pytest.mark.asyncio
async def test_provision_local_lake_records_provisioned_at_install_flow() -> None:
    """The proposed entry carries ``added_via_flow=provisioned_at_install``
    so the dashboard's source-row provenance marker can identify the
    default lake distinctly from the five user-driven flows."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )

    rows = await ledger.fetch(company_id)
    propose_args = rows[1]["payload"]["args"]
    assert propose_args["added_via_flow"] == "provisioned_at_install"
    assert propose_args["uri"] == f"local-lake://{company_id}"
    assert propose_args["source_kind"] == "database"
    assert propose_args["suggested_classification"] == "internal"
    assert propose_args["added_by_person"] == str(installer_person_id)


@pytest.mark.asyncio
async def test_provision_local_lake_confirms_with_installer() -> None:
    """The confirm entry records the installer as ``confirmed_by_person``."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )

    rows = await ledger.fetch(company_id)
    # Cycle 2 (rows 4-7): execute is at offset 1 → row 5.
    confirm_args = rows[5]["payload"]["args"]
    assert confirm_args["confirmed_by_person"] == str(installer_person_id)
    assert confirm_args["classification"] == "internal"


@pytest.mark.asyncio
async def test_provision_local_lake_writes_connection_ref() -> None:
    """The connect entry's connection_ref is the canonical
    ``local-lake://{tenant_id}`` uri so the dashboard's connector
    registry resolves it back to the LocalLakeConnector."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )

    rows = await ledger.fetch(company_id)
    # Cycle 3 (rows 8-11): execute is at offset 1 → row 9.
    connect_args = rows[9]["payload"]["args"]
    assert connect_args["connection_ref"] == f"local-lake://{company_id}"


@pytest.mark.asyncio
async def test_provision_local_lake_profiled_carries_aggregate_schema_hash() -> None:
    """The profiled entry carries an aggregate schema hash + a positive
    column count summing the 7 medallion resources."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )

    rows = await ledger.fetch(company_id)
    # Cycle 4 (rows 12-15): execute is at offset 1 → row 13.
    profile_args = rows[13]["payload"]["args"]
    assert profile_args["row_count"] == 0
    # Sum of column counts across the 7 canonical resources is well
    # over 30 (≈37). We only check the lower bound to stay tolerant of
    # future schema enrichment.
    assert profile_args["column_count"] >= 30
    assert profile_args["schema_hash"]
    assert profile_args["profile_ref"] == f"local-lake://{company_id}"


@pytest.mark.asyncio
async def test_provision_local_lake_idempotent_via_correlation_id() -> None:
    """Re-running provision_local_lake on the same tenant generates a
    fresh source_id (it doesn't dedupe by tenant); the dashboard or
    upstream caller is responsible for not calling twice. We confirm
    the function is well-behaved when invoked back-to-back: each call
    produces its own 16 entries and the chain stays intact."""
    ledger = InMemoryLedger()
    company_id = tenant_to_uuid(TENANT_SLUG)
    installer_person_id = uuid4()

    r1 = await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )
    r2 = await write_actions.provision_local_lake(
        ledger,
        company_id,
        tenant_id=company_id,
        installer_person_id=installer_person_id,
    )
    assert r1["source_id"] != r2["source_id"]
    rows = await ledger.fetch(company_id)
    assert len(rows) == 32
    ok, _ = verify_chain(rows)
    assert ok


# ---------------------------------------------------------------------------
# complete_install end-to-end now provisions the local lake automatically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_install_provisions_local_lake() -> None:
    """``complete_install`` writes its 5 PEVR cycles (20 entries) AND
    auto-provisions the local lake (4 PEVR cycles, 16 entries) — total
    36 entries. The chain remains unbroken."""
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

    assert UUID(result["install_id"])
    assert UUID(result["installer_person_id"])
    assert UUID(result["local_lake_source_id"])
    # 5 install PEVR + 4 lake PEVR = 9 cycles × 4 entries = 36 entries.
    assert len(result["entry_ids"]) == 36

    rows = await ledger.fetch(company_id)
    assert len(rows) == 36

    # Tool sequence: 5 install execs followed by 4 lake execs.
    tools = [
        rows[cycle_start + 1]["payload"]["tool"]
        for cycle_start in range(0, 36, 4)
    ]
    assert tools == [
        "emit_person_proposed",
        "emit_person_confirmed",
        "emit_role_assigned",  # tenancy.installer
        "emit_role_assigned",  # tenancy.admin
        "emit_install_completed",
        "emit_source_proposed",
        "emit_source_confirmed",
        "emit_source_connected",
        "emit_source_profiled",
    ]

    ok, broken_at = verify_chain(rows)
    assert ok and broken_at is None


@pytest.mark.asyncio
async def test_complete_install_local_lake_owned_by_installer() -> None:
    """The default lake is owned + maintained by the installer Person —
    the only Person on the tenant at install time."""
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

    rows = await ledger.fetch(company_id)
    # The first lake cycle starts at row 20 (after 5 install cycles).
    lake_propose_args = rows[21]["payload"]["args"]
    assert lake_propose_args["added_by_person"] == result["installer_person_id"]
    assert lake_propose_args["uri"] == f"local-lake://{company_id}"
    assert lake_propose_args["added_via_flow"] == "provisioned_at_install"
