"""Block H tests: KnowledgeRamp 6 axes + determinism."""

from __future__ import annotations

from uuid import uuid4

from wormbase_core.ramp import KnowledgeRamp
from wormbase_core.source_builder import (
    SourceBuilder,
    SourceProposal,
    build_full_sequence,
)
from wormbase_core.types import RampState


async def test_ramp_state_has_six_axes_each_zero_to_100(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert isinstance(state, RampState)
    for axis in ("ontology", "schema_axis", "business_definitions",
                 "kpi_relational", "conversational", "operational"):
        v = getattr(state, axis)
        assert 0.0 <= v <= 100.0


async def test_ramp_compute_is_deterministic_across_two_replays(
    ledger, company_id, clock
):
    ramp = KnowledgeRamp(ledger)
    builder = SourceBuilder(ledger, clock)
    proposal = SourceProposal(
        proposed_uri="s3://x", proposed_type="file",
        proposed_domain="g", proposed_classification="internal",
        added_via_flow="dashboard_form", company_id=company_id,
    )
    await build_full_sequence(
        builder, proposal,
        confirmer_id=uuid4(), domain_id=uuid4(), classification="internal",
        connection_fn=lambda: "c",
        profile_fn=lambda: {
            "row_count": 1, "column_count": 1,
            "schema_hash": "h", "profile_ref": "p",
        },
    )
    s1 = await ramp.compute(company_id, write_snapshot=False)
    s2 = await ramp.compute(company_id, write_snapshot=False)
    assert s1 == s2


async def test_ramp_emits_snapshot_entry(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    await ramp.compute(company_id)
    rows = await ledger.fetch(company_id)
    assert any(
        r["kind"] == "execute"
        and r["payload"]["args"].get("content") == "ramp_snapshot"
        for r in rows
    )


# Six axis behaviors ------------------------------------------------


async def test_schema_axis_zero_with_no_sources(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.schema_axis == 0.0


async def test_schema_axis_100_when_all_profiled(ledger, company_id, clock):
    ramp = KnowledgeRamp(ledger)
    builder = SourceBuilder(ledger, clock)
    proposal = SourceProposal(
        proposed_uri="s3://x", proposed_type="file",
        proposed_domain="g", proposed_classification="internal",
        added_via_flow="dashboard_form", company_id=company_id,
    )
    await build_full_sequence(
        builder, proposal,
        confirmer_id=uuid4(), domain_id=uuid4(), classification="internal",
        connection_fn=lambda: "c",
        profile_fn=lambda: {
            "row_count": 1, "column_count": 1,
            "schema_hash": "h", "profile_ref": "p",
        },
    )
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.schema_axis == 100.0


async def test_kpi_relational_axis_handles_no_kpis(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.kpi_relational == 0.0


async def test_operational_axis_zero_default(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.operational == 0.0


async def test_business_definitions_axis_handles_empty_state(ledger, company_id):
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.business_definitions == 0.0


async def test_conversational_axis_grows_with_messages(ledger, company_id, clock):
    # Simulate 50 chat_received writes by directly invoking the ledger.
    for i in range(50):
        await ledger.write(
            company_id=company_id,
            propose={"target_kind": "chat_received",
                     "ref_id": str(uuid4()),
                     "reason": "test",
                     "proposed_by": "test"},
            execute_fn=lambda i=i: {
                "tool": "channel_adapter.emit_chat_received",
                "args": {"channel_id": "C1", "message_id": str(i),
                         "sender_person": str(uuid4()),
                         "text": f"msg {i}", "classification": "internal"},
                "result_ref": str(i),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            timestamp=clock.now(),
            quadrant="active_probabilistic",
        )
    ramp = KnowledgeRamp(ledger)
    state = await ramp.compute(company_id, write_snapshot=False)
    assert state.conversational > 0
