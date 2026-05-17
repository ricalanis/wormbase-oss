"""Projection-fold tests for L1 Sub-wave A source-candidate entries.

The /lake/source-candidates dashboard surface (Sub-wave D) reads
``projection_source_candidates`` — one row per (company_id,
candidate_id) pair folded from three ledger entry kinds:

* ``source_candidate_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same candidate before resolution)
* ``source_candidate_promoted`` → UPDATE state = "promoted"
* ``source_candidate_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``source_candidate_proposed`` PEVR creates one projection
  row in state ``proposed`` with all inference fields preserved,
  including the optional ``domain_id_hint``.
* A subsequent ``source_candidate_promoted`` advances state to
  ``promoted`` + records the approving Person UUID + ts + optional
  ``downstream_source_proposed_id`` link.
* A subsequent ``source_candidate_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts (uses the
  L1-specific ``duplicate`` reason).
* Two ``source_candidate_proposed`` entries for the same candidate_id
  collapse onto one row; the LATER proposal's evidence + confidence
  + strategy + domain_id_hint + proposed_kind/identifier win
  (forward-only update; state stays "proposed").
* A promote/reject for an UNKNOWN candidate_id (no prior proposal in
  the fold's scope) is logged + skipped — no row materialised.
* Tenant isolation: rows scoped to company_id; tenant A's candidates
  do not leak into tenant B's fold.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

# Importing connectors first registers built-in connectors so the
# runtime ``proposed_kind`` validator on the proposed-payload accepts
# the canonical kinds used below.
import wormbase_lake_surfaces  # noqa: F401

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.entries import make_candidate_id
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
    candidate_id: str,
    proposed_kind: str = "stripe",
    proposed_identifier: str = "acct_q3_revenue",
    domain_id_hint: str | None = "domain-finance-1",
    strategy: str = "kpi_gap",
    reasoning: str = (
        "KPI 'q3_revenue' has no backing source; "
        "revenue KPIs typically map to Stripe."
    ),
    confidence: float = 0.72,
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``source_candidate_proposed`` PEVR cycle."""
    args = {
        "candidate_id": candidate_id,
        "proposed_kind": proposed_kind,
        "proposed_identifier": proposed_identifier,
        "strategy": strategy,
        "reasoning": reasoning,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else {"k": "v"},
    }
    if domain_id_hint is not None:
        args["domain_id_hint"] = domain_id_hint
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_proposed",
            "ref_id": str(uuid4()),
            "reason": "L1 strategy proposed source candidate",
            "proposed_by": "agent-l1-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_proposed",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_promoted(
    session,
    *,
    company_id,
    candidate_id: str,
    promoted_by_person_id: str = "person-uuid-admin",
    downstream_source_proposed_id: str | None = None,
    notes: str | None = None,
) -> None:
    """Emit a canonical ``source_candidate_promoted`` PEVR cycle."""
    args = {
        "candidate_id": candidate_id,
        "promoted_by_person_id": promoted_by_person_id,
    }
    if downstream_source_proposed_id is not None:
        args["downstream_source_proposed_id"] = downstream_source_proposed_id
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_promoted",
            "ref_id": str(uuid4()),
            "reason": "admin promoted source candidate",
            "proposed_by": promoted_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_promoted",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    candidate_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "duplicate",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``source_candidate_rejected`` PEVR cycle."""
    args = {
        "candidate_id": candidate_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "source_candidate_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected source candidate ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_rejected",
            "args": args,
            "result_ref": candidate_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_candidate_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``source_candidate_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    candidate_id = make_candidate_id(
        proposed_kind="stripe",
        proposed_identifier="acct_q3_revenue",
        strategy="kpi_gap",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            evidence={
                "kpi_node_id": "kpi-q3-revenue",
                "kpi_name_pattern": "*_revenue",
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.source_candidates) == 1
    row = proj.source_candidates[0]
    assert row["company_id"] == str(company_id)
    assert row["candidate_id"] == candidate_id
    assert row["proposed_kind"] == "stripe"
    assert row["proposed_identifier"] == "acct_q3_revenue"
    assert row["domain_id_hint"] == "domain-finance-1"
    assert row["strategy"] == "kpi_gap"
    assert row["confidence"] == pytest.approx(0.72)
    assert row["evidence"] == {
        "kpi_node_id": "kpi-q3-revenue",
        "kpi_name_pattern": "*_revenue",
    }
    assert row["downstream_source_proposed_id"] is None
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_source_candidate_proposed_no_domain_hint(
    test_database_url: str,
) -> None:
    """Strategy with no domain signal → domain_id_hint NULL on fold."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    candidate_id = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/uploads/x.csv",
        strategy="complementarity",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="csv_local",
            proposed_identifier="/uploads/x.csv",
            domain_id_hint=None,
            strategy="complementarity",
            reasoning="ad-hoc file drops not configured",
            confidence=0.45,
            evidence={},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.source_candidates) == 1
    row = proj.source_candidates[0]
    assert row["domain_id_hint"] is None
    assert row["strategy"] == "complementarity"


@pytest.mark.asyncio
async def test_source_candidate_promoted_advances_state(
    test_database_url: str,
) -> None:
    """proposed → promoted: state advances; approver UUID + ts +
    optional downstream link recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    candidate_id = make_candidate_id(
        proposed_kind="postgres",
        proposed_identifier="prod-app-db",
        strategy="complementarity",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="postgres",
            proposed_identifier="prod-app-db",
            strategy="complementarity",
        )
        await _emit_promoted(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            promoted_by_person_id="person-alice",
            downstream_source_proposed_id="entry-downstream-1",
            notes="approved",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.source_candidates) == 1
    row = proj.source_candidates[0]
    assert row["state"] == "promoted"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None
    assert row["downstream_source_proposed_id"] == "entry-downstream-1"


@pytest.mark.asyncio
async def test_source_candidate_promoted_without_downstream_link(
    test_database_url: str,
) -> None:
    """Promote without threading downstream_source_proposed_id → row
    state advances; downstream link stays NULL (Sub-wave B may promote
    without immediately linking)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    candidate_id = make_candidate_id(
        proposed_kind="snowflake",
        proposed_identifier="prod-warehouse",
        strategy="kpi_gap",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="snowflake",
            proposed_identifier="prod-warehouse",
        )
        await _emit_promoted(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            promoted_by_person_id="person-bob",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    row = proj.source_candidates[0]
    assert row["state"] == "promoted"
    assert row["downstream_source_proposed_id"] is None


@pytest.mark.asyncio
async def test_source_candidate_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + ts recorded.

    Uses the L1-specific 5th reason ``duplicate`` (distinct from L8's
    ``wrong_pairing``, L6's ``wrong_level``, L5's ``wrong_type``,
    L4's ``already_handled`` and L7's ``wrong_threshold``)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    candidate_id = make_candidate_id(
        proposed_kind="hubspot",
        proposed_identifier="account-x",
        strategy="kpi_gap",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="hubspot",
            proposed_identifier="account-x",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            rejected_by_person_id="person-bob",
            reason="duplicate",
            notes="we already have salesforce",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.source_candidates) == 1
    row = proj.source_candidates[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_candidate_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal updates evidence + confidence + reasoning +
    domain_id_hint + proposed_kind/identifier (the latest strategy's
    view). State stays "proposed" because no promote/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    # NOTE: same args → same candidate_id (deterministic dedup).
    candidate_id = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/uploads/revenue.csv",
        strategy="kpi_gap",
    )

    async with session_scope(engine) as session:
        # First proposal — weak signal, no domain hint.
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="csv_local",
            proposed_identifier="/uploads/revenue.csv",
            domain_id_hint=None,
            strategy="kpi_gap",
            reasoning="weak inference",
            confidence=0.40,
            evidence={"v": 1},
        )
        # Second proposal — refined signal, domain hint added.
        await _emit_proposed(
            session,
            company_id=company_id,
            candidate_id=candidate_id,
            proposed_kind="csv_local",
            proposed_identifier="/uploads/revenue.csv",
            domain_id_hint="domain-finance-2",
            strategy="kpi_gap",
            reasoning="stronger inference after second scan",
            confidence=0.85,
            evidence={"v": 2, "kpi_node_id": "kpi-rev"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.source_candidates) == 1
    row = proj.source_candidates[0]
    # The LATER proposal's fields win (forward-only update).
    assert row["confidence"] == pytest.approx(0.85)
    assert row["domain_id_hint"] == "domain-finance-2"
    assert row["reasoning"] == "stronger inference after second scan"
    assert row["evidence"] == {"v": 2, "kpi_node_id": "kpi-rev"}
    # State remains proposed — no promote/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown candidate_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promoted_for_unknown_candidate_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``source_candidate_promoted`` with no prior proposal logs a
    warning and skips — the fold doesn't fabricate a row from
    incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the promote.
        await _emit_promoted(
            session,
            company_id=company_id,
            candidate_id="ghost-candidate",
            promoted_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan promote.
    assert proj.source_candidates == []
    # A warning records the orphan for the operator surface.
    assert any(
        "source_candidate_promoted" in r.message
        and "ghost-candidate" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_candidate_id_is_skipped(
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
            candidate_id="ghost-candidate-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.source_candidates == []
    assert any(
        "source_candidate_rejected" in r.message
        and "ghost-candidate-2" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_candidates_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's candidates do not leak into tenant B's fold."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical candidate_id used in both tenants — composite PK
    # (company_id, candidate_id) keeps them disjoint.
    candidate_id = make_candidate_id(
        proposed_kind="csv_local",
        proposed_identifier="/uploads/shared.csv",
        strategy="kpi_gap",
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, candidate_id=candidate_id,
            reasoning="tenant A's reasoning",
            evidence={"a": 1},
        )
        await _emit_proposed(
            session, company_id=company_b, candidate_id=candidate_id,
            reasoning="tenant B's reasoning",
            evidence={"b": 1},
        )
        await _emit_promoted(
            session, company_id=company_a, candidate_id=candidate_id,
            promoted_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.source_candidates) == 1
    assert proj_a.source_candidates[0]["company_id"] == str(company_a)
    assert proj_a.source_candidates[0]["state"] == "promoted"
    assert proj_a.source_candidates[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.source_candidates) == 1
    assert proj_b.source_candidates[0]["company_id"] == str(company_b)
    # Tenant B never received the promote — stays proposed.
    assert proj_b.source_candidates[0]["state"] == "proposed"
    assert proj_b.source_candidates[0]["reasoning"] == "tenant B's reasoning"
