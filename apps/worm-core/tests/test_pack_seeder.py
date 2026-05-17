"""Tests for ``onboarding.pack_seeder`` — Onboarding Sub-wave C (2026-05-30).

Pins:

* ``seed_pack`` writes the ``domain_pack_selected`` parent PEVR cycle.
* ``seed_pack`` fans out one ``emit_domain_registered`` execute per
  pack domain.
* ``seed_pack`` fans out one ``emit_policy_applied`` execute per
  pack policy.
* Idempotency: a second call on the same tenant short-circuits with
  ``already_seeded=True`` and writes zero new entries.
* The parent entry carries the right (pack_id, pack_version,
  selected_by_person_id) — wire-replay determinism.
* Unknown pack_id raises ``PackLoadError`` before any write.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_core.onboarding.pack_loader import PackLoadError
from wormbase_core.onboarding.pack_seeder import PackSeedReport, seed_pack
from wormbase_ledger import InMemoryLedger


@pytest.fixture
def memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


@pytest.fixture
def company_id() -> UUID:
    return UUID("00000000-0000-0000-0000-0000000000aa")


@pytest.fixture
def admin_id() -> UUID:
    return UUID("00000000-0000-0000-0000-0000000000bb")


def _count_execute_entries_by_tool(rows: list[dict], tool: str) -> int:
    count = 0
    for r in rows:
        if r.get("kind") != "execute":
            continue
        if r.get("payload", {}).get("tool") == tool:
            count += 1
    return count


def _find_domain_pack_selected_execute(rows: list[dict]) -> dict | None:
    for r in rows:
        if r.get("kind") != "execute":
            continue
        args = r.get("payload", {}).get("args", {})
        if args.get("__from_kind") == "domain_pack_selected":
            return args
    return None


async def test_seed_pack_writes_parent_entry(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """First-time seed writes the domain_pack_selected parent + fan-out."""
    report = await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="generic",
        selected_by_person_id=admin_id,
    )
    assert isinstance(report, PackSeedReport)
    assert report.already_seeded is False
    assert report.pack_id == "generic"
    assert report.pack_version == "v1.0"

    rows = await memory_ledger.fetch(company_id)
    parent = _find_domain_pack_selected_execute(rows)
    assert parent is not None
    assert parent["pack_id"] == "generic"
    assert parent["pack_version"] == "v1.0"
    assert parent["selected_by_person_id"] == str(admin_id)


async def test_seed_pack_fans_out_domains(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """One emit_domain_registered execute per pack domain (saas has 4)."""
    report = await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="saas",
        selected_by_person_id=admin_id,
    )
    rows = await memory_ledger.fetch(company_id)
    domain_executes = _count_execute_entries_by_tool(rows, "emit_domain_registered")
    assert domain_executes == len(report.domain_ids)
    assert domain_executes == 4  # saas pack ships 4 domains


async def test_seed_pack_fans_out_policies(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """One emit_policy_applied execute per pack policy."""
    report = await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="saas",
        selected_by_person_id=admin_id,
    )
    rows = await memory_ledger.fetch(company_id)
    policy_executes = _count_execute_entries_by_tool(rows, "emit_policy_applied")
    assert policy_executes == len(report.policy_ids)
    assert policy_executes >= 1


async def test_seed_pack_idempotent(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """Re-running on the same tenant short-circuits with already_seeded=True."""
    first = await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="generic",
        selected_by_person_id=admin_id,
    )
    assert first.already_seeded is False

    rows_after_first = await memory_ledger.fetch(company_id)
    count_first = len(rows_after_first)

    second = await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="generic",
        selected_by_person_id=admin_id,
    )
    assert second.already_seeded is True

    rows_after_second = await memory_ledger.fetch(company_id)
    assert len(rows_after_second) == count_first, (
        "idempotent seed must write zero new entries"
    )


async def test_seed_pack_unknown_id_raises(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """Unknown pack_id raises PackLoadError BEFORE any ledger write."""
    rows_before = await memory_ledger.fetch(company_id)
    with pytest.raises(PackLoadError):
        await seed_pack(
            memory_ledger,
            company_id=company_id,
            pack_id="nope",
            selected_by_person_id=admin_id,
        )
    rows_after = await memory_ledger.fetch(company_id)
    assert len(rows_before) == len(rows_after), (
        "no writes should land when pack_id is unknown"
    )


async def test_seed_pack_carries_notes(
    memory_ledger: InMemoryLedger, company_id: UUID, admin_id: UUID,
) -> None:
    """Optional notes round-trip into the parent entry's payload."""
    await seed_pack(
        memory_ledger,
        company_id=company_id,
        pack_id="generic",
        selected_by_person_id=admin_id,
        notes="Tier 2 baseline at install time T0",
    )
    rows = await memory_ledger.fetch(company_id)
    parent = _find_domain_pack_selected_execute(rows)
    assert parent is not None
    assert parent["notes"] == "Tier 2 baseline at install time T0"


async def test_seed_pack_different_tenants_isolated() -> None:
    """Idempotency is per-tenant — tenant B can seed after tenant A did."""
    ledger = InMemoryLedger()
    tenant_a = UUID("00000000-0000-0000-0000-00000000000a")
    tenant_b = UUID("00000000-0000-0000-0000-00000000000b")
    admin = uuid4()

    ra = await seed_pack(
        ledger,
        company_id=tenant_a,
        pack_id="generic",
        selected_by_person_id=admin,
    )
    assert ra.already_seeded is False

    rb = await seed_pack(
        ledger,
        company_id=tenant_b,
        pack_id="generic",
        selected_by_person_id=admin,
    )
    assert rb.already_seeded is False, (
        "tenant B should not be short-circuited by tenant A's prior pick"
    )
