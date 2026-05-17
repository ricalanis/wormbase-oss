"""Projection-fold tests for L3 Sub-wave A lineage-edge entries.

The /lake/lineage dashboard surface (Sub-wave D) reads
``projection_lineage_edges`` — one row per (company_id, edge_id) pair
folded from three ledger entry kinds:

* ``lineage_edge_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same edge before resolution)
* ``lineage_edge_confirmed`` → UPDATE state = "confirmed"
* ``lineage_edge_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``lineage_edge_proposed`` PEVR creates one projection row
  in state ``proposed`` with all inference fields preserved.
* A subsequent ``lineage_edge_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``lineage_edge_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts.
* Two ``lineage_edge_proposed`` entries for the same edge_id collapse
  onto one row; the LATER proposal's evidence + confidence + strategy
  win (forward-only update; state stays "proposed").
* A confirm/reject for an UNKNOWN edge_id (no prior proposal in the
  fold's scope) is logged + skipped — no row materialised.
* A forward-only state cycle (proposed → confirmed → rejected →
  confirmed) lands the final state on the projection row.
* Tenant isolation: rows scoped to company_id; tenant A's edges do
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
    edge_id: str,
    src_table_id: str = "src-1.public.orders",
    src_column: str | None = "customer_id",
    tgt_table_id: str = "src-2.public.customers",
    tgt_column: str | None = "id",
    confidence: float = 0.87,
    strategy: str = "sample_overlap",
    reasoning: str = "high jaccard overlap",
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``lineage_edge_proposed`` PEVR cycle."""
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_proposed",
            "ref_id": str(uuid4()),
            "reason": "inference strategy proposed edge",
            "proposed_by": "agent-l3-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_proposed",
            "args": {
                "edge_id": edge_id,
                "src_table_id": src_table_id,
                "src_column": src_column,
                "tgt_table_id": tgt_table_id,
                "tgt_column": tgt_column,
                "confidence": confidence,
                "strategy": strategy,
                "reasoning": reasoning,
                "evidence": evidence if evidence is not None else {"k": "v"},
            },
            "result_ref": edge_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    edge_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``lineage_edge_confirmed`` PEVR cycle."""
    args = {
        "edge_id": edge_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved edge",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_confirmed",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    edge_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "false_positive",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``lineage_edge_rejected`` PEVR cycle."""
    args = {
        "edge_id": edge_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "lineage_edge_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected edge ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_rejected",
            "args": args,
            "result_ref": edge_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lineage_edge_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``lineage_edge_proposed`` PEVR → one row in lineage_edges (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    edge_id = "edge-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, edge_id=edge_id,
            evidence={"sample_overlap_ratio": 0.87, "sampled_n": 1000},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.lineage_edges) == 1
    row = proj.lineage_edges[0]
    assert row["company_id"] == str(company_id)
    assert row["edge_id"] == edge_id
    assert row["src_table_id"] == "src-1.public.orders"
    assert row["src_column"] == "customer_id"
    assert row["tgt_table_id"] == "src-2.public.customers"
    assert row["tgt_column"] == "id"
    assert row["confidence"] == pytest.approx(0.87)
    assert row["strategy"] == "sample_overlap"
    assert row["reasoning"] == "high jaccard overlap"
    assert row["evidence"] == {"sample_overlap_ratio": 0.87, "sampled_n": 1000}
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_lineage_edge_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    edge_id = "edge-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, edge_id=edge_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            edge_id=edge_id,
            confirmed_by_person_id="person-alice",
            notes="verified via staging",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.lineage_edges) == 1
    row = proj.lineage_edges[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_lineage_edge_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    edge_id = "edge-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, edge_id=edge_id)
        await _emit_rejected(
            session,
            company_id=company_id,
            edge_id=edge_id,
            rejected_by_person_id="person-bob",
            reason="false_positive",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.lineage_edges) == 1
    row = proj.lineage_edges[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_edge_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a different strategy) updates evidence +
    confidence + strategy + reasoning. State stays "proposed" because no
    confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    edge_id = "edge-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — naming_heuristic with low confidence.
        await _emit_proposed(
            session,
            company_id=company_id,
            edge_id=edge_id,
            confidence=0.6,
            strategy="naming_heuristic",
            reasoning="similar column names",
            evidence={"edit_distance": 2},
        )
        # Second proposal — sample_overlap with high confidence (the
        # composite service deduped onto the same edge_id; the later
        # observation wins).
        await _emit_proposed(
            session,
            company_id=company_id,
            edge_id=edge_id,
            confidence=0.95,
            strategy="sample_overlap",
            reasoning="95% value overlap on 5000 sampled rows",
            evidence={"sample_overlap_ratio": 0.95, "sampled_n": 5000},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.lineage_edges) == 1
    row = proj.lineage_edges[0]
    # The LATER proposal's evidence wins (forward-only update; the row
    # surfaces the inference field the operator should see today).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "sample_overlap"
    assert row["reasoning"] == "95% value overlap on 5000 sampled rows"
    assert row["evidence"] == {"sample_overlap_ratio": 0.95, "sampled_n": 5000}
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown edge_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_edge_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``lineage_edge_confirmed`` with no prior proposal logs a warning
    and skips — the fold doesn't fabricate a row from incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            edge_id="edge-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.lineage_edges == []
    # A warning records the orphan for the operator surface.
    assert any(
        "lineage_edge_confirmed" in r.message and "edge-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_edge_id_is_skipped(
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
            edge_id="edge-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.lineage_edges == []
    assert any(
        "lineage_edge_rejected" in r.message and "edge-ghost-2" in r.message
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
    edge_id = "edge-flip-flop"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, edge_id=edge_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            edge_id=edge_id,
            confirmed_by_person_id="person-1",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            edge_id=edge_id,
            rejected_by_person_id="person-2",
            reason="wrong_direction",
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            edge_id=edge_id,
            confirmed_by_person_id="person-3",
            notes="re-validated after data refresh",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.lineage_edges) == 1
    row = proj.lineage_edges[0]
    # Final state is the LATEST forward-only write.
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-3"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lineage_edges_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's edges do not leak into tenant B's fold (and vice versa)."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical edge_id used in both tenants — composite PK
    # (company_id, edge_id) keeps them disjoint.
    edge_id = "edge-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, edge_id=edge_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, edge_id=edge_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, edge_id=edge_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.lineage_edges) == 1
    assert proj_a.lineage_edges[0]["company_id"] == str(company_a)
    assert proj_a.lineage_edges[0]["state"] == "confirmed"
    assert proj_a.lineage_edges[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.lineage_edges) == 1
    assert proj_b.lineage_edges[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.lineage_edges[0]["state"] == "proposed"
    assert proj_b.lineage_edges[0]["reasoning"] == "tenant B's reasoning"
