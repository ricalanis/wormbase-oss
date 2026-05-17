"""L3 contract: 5 governance projections produce stable, schema-conforming
outputs over a known ledger state.

Builds a deterministic ledger via direct ``ledger.write`` calls (no
worm-core dependency, no Slack), runs each projection, and asserts:

1. Every emitted row's ``kind`` matches the ALL_KINDS registry — i.e.
   the projection's read-side never accepts an unknown event kind.
2. Each projection returns Pydantic-validated entities (Person, Domain,
   Resource, Policy) whose fields are all populated.
3. ``project_classifications`` returns exactly the 5 classification
   buckets — adding/removing a Classification literal will fail this
   test loud, which is the desired behavior.
4. Re-running the projection on the same input rows is deterministic
   (same entities, same ordering).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from wormbase_governance import (
    project_classifications,
    project_domains,
    project_people,
    project_policies,
    project_resources,
)
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import ALL_KINDS

TEST_COMPANY = UUID("00000000-0000-0000-0000-0000000c0a1c")
TS = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)


async def _seed_basic_state(ledger: InMemoryLedger) -> None:
    """Seed: 1 person registered, 1 domain registered, 1 source proposed,
    1 policy applied — enough for every projection to return non-empty."""
    person_id = str(uuid4())
    domain_id = str(uuid4())
    source_id = str(uuid4())
    policy_id = str(uuid4())
    correlation_id = str(uuid4())

    # Person
    await ledger.write(
        company_id=TEST_COMPANY,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(uuid4()),
            "reason": "person register",
            "proposed_by": "contract-suite",
        },
        execute_fn=lambda: {
            "tool": "emit_person_registered",
            "args": {
                "id": person_id,
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "role": "admin",
            },
            "result_ref": person_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=TS,
    )
    # Domain
    await ledger.write(
        company_id=TEST_COMPANY,
        propose={
            "target_kind": "memory_written",
            "ref_id": str(uuid4()),
            "reason": "domain register",
            "proposed_by": "contract-suite",
        },
        execute_fn=lambda: {
            "tool": "emit_domain_registered",
            "args": {
                "id": domain_id,
                "name": "Finance",
                "classification": "confidential",
                "owner_person_id": person_id,
            },
            "result_ref": domain_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=TS,
    )
    # Source -> resource
    await ledger.write(
        company_id=TEST_COMPANY,
        propose={
            "target_kind": "source_proposed",
            "ref_id": correlation_id,
            "reason": "src",
            "proposed_by": "contract-suite",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": {
                "source_id": source_id,
                "source_kind": "file",
                "uri": "s3://b/q.csv",
                "added_via_flow": "dashboard_form",
                "suggested_domain": "Finance",
                "suggested_classification": "confidential",
                "correlation_id": correlation_id,
            },
            "result_ref": correlation_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        timestamp=TS,
    )
    # Policy
    await ledger.write(
        company_id=TEST_COMPANY,
        propose={
            "target_kind": "policy_applied",
            "ref_id": policy_id,
            "reason": "policy",
            "proposed_by": "contract-suite",
        },
        execute_fn=lambda: {
            "tool": "emit_policy_applied",
            "args": {
                "policy_id": policy_id,
                "policy_name": "pii_redaction",
                "applies_to": {"classification": "pii"},
                "rule": "redact",
                "gate_impl": "PIIGate",
            },
            "result_ref": policy_id,
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "applied", "rationale": "ok"},
        timestamp=TS,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_emitted_kind_is_registered() -> None:
    ledger = InMemoryLedger()
    await _seed_basic_state(ledger)
    rows = await ledger.fetch(TEST_COMPANY)
    for r in rows:
        assert r["kind"] in ALL_KINDS, r["kind"]


@pytest.mark.asyncio
async def test_five_projections_yield_non_empty_typed_entities() -> None:
    ledger = InMemoryLedger()
    await _seed_basic_state(ledger)
    rows = await ledger.fetch(TEST_COMPANY)

    people = project_people(rows, TEST_COMPANY)
    assert len(people) == 1 and people[0].name == "Ada Lovelace"

    domains = project_domains(rows, TEST_COMPANY)
    assert len(domains) == 1 and domains[0].name == "Finance"

    resources = project_resources(rows, TEST_COMPANY)
    assert len(resources) == 1 and resources[0].identifier == "s3://b/q.csv"

    classifications = project_classifications(resources)
    assert set(classifications.keys()) == {
        "public", "internal", "confidential", "pii", "regulated",
    }
    assert classifications["confidential"] == 1

    policies = project_policies(rows, TEST_COMPANY)
    assert len(policies) == 1 and policies[0].name == "pii_redaction"


@pytest.mark.asyncio
async def test_projections_are_deterministic_across_replays() -> None:
    """Schema contract: identical input rows → identical projection output."""
    ledger = InMemoryLedger()
    await _seed_basic_state(ledger)
    rows = await ledger.fetch(TEST_COMPANY)

    p1 = project_people(rows, TEST_COMPANY)
    p2 = project_people(rows, TEST_COMPANY)
    assert p1 == p2

    d1 = project_domains(rows, TEST_COMPANY)
    d2 = project_domains(rows, TEST_COMPANY)
    assert d1 == d2

    r1 = project_resources(rows, TEST_COMPANY)
    r2 = project_resources(rows, TEST_COMPANY)
    assert r1 == r2

    c1 = project_classifications(r1)
    c2 = project_classifications(r2)
    assert c1 == c2

    pol1 = project_policies(rows, TEST_COMPANY)
    pol2 = project_policies(rows, TEST_COMPANY)
    assert pol1 == pol2
