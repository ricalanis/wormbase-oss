"""Block J tests: PolicyLoader + CompanyWarmup."""

from __future__ import annotations

import importlib

from wormbase_governance import CompanyWarmup, PolicyLoader


async def test_policy_loader_writes_three_templates(ledger, company_id):
    loader = PolicyLoader(ledger)
    policies = await loader.load_templates(company_id, "saas")
    assert len(policies) >= 3
    rows = await ledger.fetch(company_id)
    applied = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_policy_applied"
    ]
    assert len(applied) >= 3


async def test_policy_loader_idempotent_on_second_run(ledger, company_id):
    loader = PolicyLoader(ledger)
    first = await loader.load_templates(company_id, "saas")
    second = await loader.load_templates(company_id, "saas")
    assert second == []  # nothing new
    rows = await ledger.fetch(company_id)
    applied = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_policy_applied"
    ]
    assert len(applied) == len(first)


async def test_policy_gate_impl_paths_are_importable(ledger, company_id):
    loader = PolicyLoader(ledger)
    policies = await loader.load_templates(company_id, "saas")
    for p in policies:
        # Should be a real importable dotted path: module.callable.
        module_path, _, name = p.gate_impl.rpartition(".")
        mod = importlib.import_module(module_path)
        assert hasattr(mod, name), f"{p.gate_impl} not found"


async def test_warmup_loads_domains_policies_and_marks_complete(ledger, company_id):
    warmup = CompanyWarmup(ledger)
    report = await warmup.warmup(company_id, "saas")
    assert not report.already_warm
    assert len(report.domains) >= 3
    assert len(report.policies) >= 3
    # Re-running should be a no-op.
    report2 = await warmup.warmup(company_id, "saas")
    assert report2.already_warm


async def test_warmup_supports_marketplace_and_fintech(ledger, company_id):
    from uuid import uuid4
    warm_a = CompanyWarmup(ledger)
    a = uuid4()
    b = uuid4()
    rep_m = await warm_a.warmup(a, "marketplace")
    rep_f = await warm_a.warmup(b, "fintech")
    assert {d for d in rep_m.domains} != {d for d in rep_f.domains}
