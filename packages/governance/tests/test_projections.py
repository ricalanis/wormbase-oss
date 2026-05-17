"""Tests for governance projections — uses direct ledger writes (no worm-core dep)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from wormbase_governance import (
    CompanyWarmup,
    project_classifications,
    project_domains,
    project_policies,
    project_resources,
)


async def _propose_source(ledger, company_id, *, uri, kind="file",
                          classification="internal"):
    """Mirror SourceBuilder.propose without depending on worm-core."""
    source_id = str(uuid4())
    correlation_id = str(uuid4())
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_proposed",
            "ref_id": correlation_id,
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": {
                "source_id": source_id,
                "source_kind": kind,
                "uri": uri,
                "added_via_flow": "dashboard_form",
                "suggested_domain": "general",
                "suggested_classification": classification,
                "correlation_id": correlation_id,
            },
            "result_ref": correlation_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )


async def test_warmup_then_project_domains(ledger, company_id):
    warmup = CompanyWarmup(ledger)
    await warmup.warmup(company_id, "saas")
    rows = await ledger.fetch(company_id)
    domains = project_domains(rows, company_id)
    assert len(domains) >= 3
    names = {d.name for d in domains}
    assert "Product" in names
    assert "Finance" in names


async def test_warmup_then_project_policies(ledger, company_id):
    warmup = CompanyWarmup(ledger)
    await warmup.warmup(company_id, "saas")
    rows = await ledger.fetch(company_id)
    policies = project_policies(rows, company_id)
    assert len(policies) >= 3


async def test_project_resources_after_source_proposal(ledger, company_id):
    await _propose_source(ledger, company_id, uri="s3://bucket/data.csv")
    rows = await ledger.fetch(company_id)
    resources = project_resources(rows, company_id)
    assert len(resources) == 1
    assert resources[0].type == "source"


async def test_project_classifications_aggregates(ledger, company_id):
    await _propose_source(ledger, company_id, uri="a", classification="internal")
    await _propose_source(ledger, company_id, uri="b", classification="pii")
    await _propose_source(ledger, company_id, uri="c", classification="internal")
    rows = await ledger.fetch(company_id)
    counts = project_classifications(project_resources(rows, company_id))
    assert counts["internal"] == 2
    assert counts["pii"] == 1


async def test_projections_respect_company_id_scope(ledger):
    a, b = uuid4(), uuid4()
    await _propose_source(ledger, a, uri="s3://a")
    await _propose_source(ledger, b, uri="s3://b")
    rows_a = await ledger.fetch(a)
    rows_b = await ledger.fetch(b)
    res_a = project_resources(rows_a, a)
    res_b = project_resources(rows_b, b)
    assert len(res_a) == 1
    assert len(res_b) == 1
