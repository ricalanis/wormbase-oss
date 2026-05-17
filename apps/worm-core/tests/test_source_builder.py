"""Block E base tests: SourceBuilder canonical 4-stage sequence."""

from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_core.source_builder import (
    SourceBuilder,
    SourceBuilderStateError,
    SourceProposal,
    build_full_sequence,
)


def make_proposal(company_id, *, flow="drop_and_profile", correlation_id=None):
    return SourceProposal(
        proposed_uri="s3://bucket/data.csv",
        proposed_type="file",
        proposed_domain="finance",
        proposed_classification="internal",
        proposed_owner_person_id=uuid4(),
        added_by_person_id=uuid4(),
        added_via_flow=flow,
        added_in_response_to="msg:123",
        correlation_id=correlation_id or str(uuid4()),
        company_id=company_id,
    )


async def test_propose_writes_source_proposed(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(make_proposal(company_id))
    rows = await ledger.fetch(company_id)
    proposes = [r for r in rows if r["kind"] == "execute"
                and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposes) == 1
    assert proposes[0]["payload"]["args"]["correlation_id"] == str(cid)


async def test_full_sequence_writes_four_lifecycle_entries(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    proposal = make_proposal(company_id)
    cid = await build_full_sequence(
        builder, proposal,
        confirmer_id=uuid4(),
        domain_id=uuid4(),
        classification="internal",
        connection_fn=lambda: "conn-handle-1",
        profile_fn=lambda: {
            "row_count": 100,
            "column_count": 5,
            "schema_hash": "abc",
            "profile_ref": "prof-1",
        },
    )
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_source_proposed" in tools
    assert "emit_source_confirmed" in tools
    assert "emit_source_connected" in tools
    assert "emit_source_profiled" in tools
    assert str(cid)


async def test_rejects_confirm_without_propose(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    with pytest.raises(SourceBuilderStateError):
        await builder.confirm("never-proposed", uuid4(), uuid4(), "internal")


async def test_rejects_connect_without_confirm(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    cid = await builder.propose(make_proposal(company_id))
    with pytest.raises(SourceBuilderStateError):
        await builder.connect(str(cid), "handle")


async def test_idempotent_on_duplicate_correlation_id(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    fixed_cid = "fixed-cid-1"
    p1 = make_proposal(company_id, correlation_id=fixed_cid)
    p2 = make_proposal(company_id, correlation_id=fixed_cid)
    await builder.propose(p1)
    await builder.propose(p2)
    rows = await ledger.fetch(company_id)
    proposes = [r for r in rows if r["kind"] == "execute"
                and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposes) == 1


async def test_full_sequence_rolls_back_on_profile_failure(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)

    def bad_profile():
        raise RuntimeError("profile failed")

    with pytest.raises(RuntimeError):
        await build_full_sequence(
            builder, make_proposal(company_id),
            confirmer_id=uuid4(),
            domain_id=uuid4(),
            classification="internal",
            connection_fn=lambda: "conn",
            profile_fn=bad_profile,
        )
    rows = await ledger.fetch(company_id)
    tags_with_aborted = [
        r for r in rows
        if r["kind"] == "execute"
        and "source_aborted" in r["payload"]["args"].get("tags", [])
    ]
    assert len(tags_with_aborted) == 1
