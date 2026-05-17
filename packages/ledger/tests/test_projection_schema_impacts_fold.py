"""Projection-fold tests for L4 Sub-wave A schema-impact entries.

The /lake/schema-impacts dashboard surface (Sub-wave D) reads
``projection_schema_impacts`` — one row per (company_id, impact_id) pair
folded from three ledger entry kinds:

* ``schema_impact_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same impact before resolution)
* ``schema_impact_confirmed`` → UPDATE state = "confirmed"
* ``schema_impact_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``schema_impact_proposed`` PEVR creates one projection row
  in state ``proposed`` with all inference fields preserved.
* A subsequent ``schema_impact_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``schema_impact_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts.
* Two ``schema_impact_proposed`` entries for the same impact_id collapse
  onto one row; the LATER proposal's evidence + confidence + strategy
  win (forward-only update; state stays "proposed").
* A confirm/reject for an UNKNOWN impact_id (no prior proposal in the
  fold's scope) is logged + skipped — no row materialised.
* A forward-only state cycle (proposed → confirmed → rejected →
  confirmed) lands the final state on the projection row.
* Tenant isolation: rows scoped to company_id; tenant A's impacts do
  not leak into tenant B's fold.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r):  # type: ignore[no-untyped-def]
    return {"checks": [], "passed": True}


def _resolve_keep(_v):  # type: ignore[no-untyped-def]
    return {"outcome": "keep", "rationale": "ok"}


async def _emit_proposed(
    session,
    *,
    company_id,
    impact_id: str,
    source_id: str = "src-stripe-1",
    src_table: str = "public.charges",
    src_column: str = "amount_minor",
    change_kind: str = "column_type_changed",
    impact_kind: str = "tgt_column_type_mismatch",
    tgt_table_id: str = "warehouse.fct_charges",
    tgt_column: str = "amount_cents",
    upstream_lineage_edge_id: str | None = "edge-1",
    confidence: float = 0.92,
    strategy: str = "lineage_edge",
    reasoning: str = "lineage edge predicts downstream impact",
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``schema_impact_proposed`` PEVR cycle."""
    args = {
        "impact_id": impact_id,
        "source_id": source_id,
        "src_table": src_table,
        "src_column": src_column,
        "change_kind": change_kind,
        "impact_kind": impact_kind,
        "tgt_table_id": tgt_table_id,
        "tgt_column": tgt_column,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": reasoning,
        "evidence": evidence if evidence is not None else {"k": "v"},
    }
    if upstream_lineage_edge_id is not None:
        args["upstream_lineage_edge_id"] = upstream_lineage_edge_id
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "schema_impact_proposed",
            "ref_id": str(uuid4()),
            "reason": "L4 strategy proposed impact",
            "proposed_by": "agent-l4-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_schema_impact_proposed",
            "args": args,
            "result_ref": impact_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    impact_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``schema_impact_confirmed`` PEVR cycle."""
    args = {
        "impact_id": impact_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "schema_impact_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved impact",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_schema_impact_confirmed",
            "args": args,
            "result_ref": impact_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    impact_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "false_positive",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``schema_impact_rejected`` PEVR cycle."""
    args = {
        "impact_id": impact_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "schema_impact_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected impact ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_schema_impact_rejected",
            "args": args,
            "result_ref": impact_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_impact_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``schema_impact_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, impact_id=impact_id,
            evidence={"upstream_change_seq": 1234, "downstream_type": "INTEGER"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    assert row["company_id"] == str(company_id)
    assert row["impact_id"] == impact_id
    assert row["source_id"] == "src-stripe-1"
    assert row["src_table"] == "public.charges"
    assert row["src_column"] == "amount_minor"
    assert row["change_kind"] == "column_type_changed"
    assert row["impact_kind"] == "tgt_column_type_mismatch"
    assert row["tgt_table_id"] == "warehouse.fct_charges"
    assert row["tgt_column"] == "amount_cents"
    assert row["upstream_lineage_edge_id"] == "edge-1"
    assert row["confidence"] == pytest.approx(0.92)
    assert row["strategy"] == "lineage_edge"
    assert row["reasoning"] == "lineage edge predicts downstream impact"
    assert row["evidence"] == {
        "upstream_change_seq": 1234,
        "downstream_type": "INTEGER",
    }
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_schema_impact_proposed_with_null_upstream_edge(
    test_database_url: str,
) -> None:
    """type_coercion proposals carry NULL upstream_lineage_edge_id."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-type-coerce-1"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, impact_id=impact_id,
            strategy="type_coercion",
            upstream_lineage_edge_id=None,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    assert row["strategy"] == "type_coercion"
    assert row["upstream_lineage_edge_id"] is None


@pytest.mark.asyncio
async def test_schema_impact_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, impact_id=impact_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            impact_id=impact_id,
            confirmed_by_person_id="person-alice",
            notes="downstream pipeline patched",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_schema_impact_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, impact_id=impact_id)
        await _emit_rejected(
            session,
            company_id=company_id,
            impact_id=impact_id,
            rejected_by_person_id="person-bob",
            reason="already_handled",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_impact_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a different strategy) updates evidence +
    confidence + strategy + reasoning + upstream_lineage_edge_id. State
    stays "proposed" because no confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — type_coercion with low confidence, no edge.
        await _emit_proposed(
            session,
            company_id=company_id,
            impact_id=impact_id,
            confidence=0.6,
            strategy="type_coercion",
            reasoning="sample-stat detected type drift",
            upstream_lineage_edge_id=None,
            evidence={"observed_types": ["int", "bigint"]},
        )
        # Second proposal — lineage_edge with high confidence + edge ref.
        await _emit_proposed(
            session,
            company_id=company_id,
            impact_id=impact_id,
            confidence=0.95,
            strategy="lineage_edge",
            reasoning="L3 confirmed edge predicts impact",
            upstream_lineage_edge_id="edge-confirmed-1",
            evidence={"upstream_change_seq": 5678},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    # The LATER proposal's fields win (forward-only update; the row
    # surfaces the inference field the operator should see today).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "lineage_edge"
    assert row["reasoning"] == "L3 confirmed edge predicts impact"
    assert row["upstream_lineage_edge_id"] == "edge-confirmed-1"
    assert row["evidence"] == {"upstream_change_seq": 5678}
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown impact_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_impact_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``schema_impact_confirmed`` with no prior proposal logs a warning
    and skips — the fold doesn't fabricate a row from incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            impact_id="impact-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.schema_impacts == []
    # A warning records the orphan for the operator surface.
    assert any(
        "schema_impact_confirmed" in r.message and "impact-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_impact_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """Symmetric guard: rejection without prior proposal logs + skips."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _emit_rejected(
            session,
            company_id=company_id,
            impact_id="impact-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.schema_impacts == []
    assert any(
        "schema_impact_rejected" in r.message and "impact-ghost-2" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Forward-only state cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_cycle_proposed_confirmed_rejected_confirmed(
    test_database_url: str,
) -> None:
    """Forward-only state transitions: each emit lands a new ledger entry,
    the fold advances the projection row's state to the latest write.

    proposed → confirmed → rejected → confirmed: the final state is
    "confirmed" because the last forward-only write was a confirmation.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    impact_id = "impact-flip-flop"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, impact_id=impact_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            impact_id=impact_id,
            confirmed_by_person_id="person-1",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            impact_id=impact_id,
            rejected_by_person_id="person-2",
            reason="already_handled",
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            impact_id=impact_id,
            confirmed_by_person_id="person-3",
            notes="re-validated after data refresh",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.schema_impacts) == 1
    row = proj.schema_impacts[0]
    # Final state is the LATEST forward-only write.
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-3"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_impacts_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's impacts do not leak into tenant B's fold (and vice versa)."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical impact_id used in both tenants — composite PK
    # (company_id, impact_id) keeps them disjoint.
    impact_id = "impact-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, impact_id=impact_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, impact_id=impact_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, impact_id=impact_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.schema_impacts) == 1
    assert proj_a.schema_impacts[0]["company_id"] == str(company_a)
    assert proj_a.schema_impacts[0]["state"] == "confirmed"
    assert proj_a.schema_impacts[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.schema_impacts) == 1
    assert proj_b.schema_impacts[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.schema_impacts[0]["state"] == "proposed"
    assert proj_b.schema_impacts[0]["reasoning"] == "tenant B's reasoning"
