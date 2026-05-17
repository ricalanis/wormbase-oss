"""L5 integration: company warmup seeds the ledger with domains + policies.

After ``CompanyWarmup.warmup`` runs against a fresh tenant:

1. The ledger has ≥1 ``emit_domain_registered`` and ≥1
   ``emit_policy_applied`` execute entry.
2. Re-running warmup is idempotent — same domain/policy ledger row
   counts, same names, no duplicates.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


def _count_executes(rows: list[dict], tool: str) -> int:
    return sum(
        1 for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == tool
    )


@pytest.mark.asyncio
async def test_warmup_writes_domains_and_policies_then_is_idempotent(
    integration_ledger,
) -> None:
    from wormbase_governance import CompanyWarmup

    company_id = uuid4()
    warmup = CompanyWarmup(integration_ledger)

    # First call — fresh tenant.
    report1 = await warmup.warmup(company_id, "saas")
    assert not report1.already_warm
    assert len(report1.domains) >= 1
    assert len(report1.policies) >= 1

    rows_after_1 = await integration_ledger.fetch(company_id)
    domain_writes_1 = _count_executes(rows_after_1, "emit_domain_registered")
    policy_writes_1 = _count_executes(rows_after_1, "emit_policy_applied")
    assert domain_writes_1 >= 1
    assert policy_writes_1 >= 1

    # Second call — same tenant. Must short-circuit (already_warm) and
    # write zero new ledger rows.
    report2 = await warmup.warmup(company_id, "saas")
    assert report2.already_warm

    rows_after_2 = await integration_ledger.fetch(company_id)
    domain_writes_2 = _count_executes(rows_after_2, "emit_domain_registered")
    policy_writes_2 = _count_executes(rows_after_2, "emit_policy_applied")
    assert domain_writes_2 == domain_writes_1, (
        "warmup re-run wrote duplicate emit_domain_registered entries"
    )
    assert policy_writes_2 == policy_writes_1, (
        "warmup re-run wrote duplicate emit_policy_applied entries"
    )
