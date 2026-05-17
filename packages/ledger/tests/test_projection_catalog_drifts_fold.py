"""Projection-fold tests for L2 Sub-wave A catalog-drift entries.

The /lake/catalog-drift dashboard surface (Sub-wave D) reads
``projection_catalog_drifts`` — one row per (company_id,
drift_id) pair folded from three ledger entry kinds:

* ``catalog_drift_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same drift before resolution)
* ``catalog_drift_acknowledged`` → UPDATE state = "acknowledged"
* ``catalog_drift_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``catalog_drift_proposed`` PEVR creates one projection
  row in state ``proposed`` with all inference fields preserved,
  including the optional ``column`` / ``before`` / ``after`` per
  drift_kind nullability rules.
* A subsequent ``catalog_drift_acknowledged`` advances state to
  ``acknowledged`` + records the acknowledging Person UUID + ts
  (with no downstream pipeline trigger, no cross-axis effect).
* A subsequent ``catalog_drift_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts (uses the
  L2-specific ``expected_change`` reason).
* Two ``catalog_drift_proposed`` entries for the same drift_id
  collapse onto one row; the LATER proposal's evidence + confidence
  + strategy + before/after win (forward-only update; state stays
  "proposed").
* An acknowledge/reject for an UNKNOWN drift_id (no prior proposal
  in the fold's scope) is logged + skipped — no row materialised.
* Tenant isolation: rows scoped to company_id; tenant A's drifts
  do not leak into tenant B's fold.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.entries import make_drift_id
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
    drift_id: str,
    source_id: str = "src-stripe-1",
    table_id: str = "customers",
    column: str | None = "email",
    drift_kind: str = "column_type_changed",
    before: dict | None = None,
    after: dict | None = None,
    strategy: str = "column_type",
    reasoning: str = "type widened from varchar(255) to text",
    confidence: float = 0.90,
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``catalog_drift_proposed`` PEVR cycle."""
    if before is None and drift_kind not in ("table_added", "column_added"):
        before = {"type": "varchar(255)"}
    if after is None and drift_kind not in ("table_removed", "column_removed"):
        after = {"type": "text"}
    args = {
        "drift_id": drift_id,
        "source_id": source_id,
        "table_id": table_id,
        "drift_kind": drift_kind,
        "strategy": strategy,
        "reasoning": reasoning,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else {"k": "v"},
    }
    if column is not None:
        args["column"] = column
    if before is not None:
        args["before"] = before
    if after is not None:
        args["after"] = after
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_proposed",
            "ref_id": str(uuid4()),
            "reason": "L2 strategy detected catalog drift",
            "proposed_by": "agent-l2-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_proposed",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_acknowledged(
    session,
    *,
    company_id,
    drift_id: str,
    acknowledged_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``catalog_drift_acknowledged`` PEVR cycle."""
    args = {
        "drift_id": drift_id,
        "acknowledged_by_person_id": acknowledged_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_acknowledged",
            "ref_id": str(uuid4()),
            "reason": "admin acknowledged catalog drift",
            "proposed_by": acknowledged_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_acknowledged",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    drift_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "expected_change",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``catalog_drift_rejected`` PEVR cycle."""
    args = {
        "drift_id": drift_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "catalog_drift_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected catalog drift ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_rejected",
            "args": args,
            "result_ref": drift_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_drift_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``catalog_drift_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    drift_id = make_drift_id(
        source_id="src-stripe-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            evidence={
                "before_type": "varchar(255)",
                "after_type": "text",
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_drifts) == 1
    row = proj.catalog_drifts[0]
    assert row["company_id"] == str(company_id)
    assert row["drift_id"] == drift_id
    assert row["source_id"] == "src-stripe-1"
    assert row["table_id"] == "customers"
    assert row["column"] == "email"
    assert row["drift_kind"] == "column_type_changed"
    assert row["before"] == {"type": "varchar(255)"}
    assert row["after"] == {"type": "text"}
    assert row["strategy"] == "column_type"
    assert row["confidence"] == pytest.approx(0.90)
    assert row["evidence"] == {
        "before_type": "varchar(255)",
        "after_type": "text",
    }
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_catalog_drift_proposed_table_added_null_column_before(
    test_database_url: str,
) -> None:
    """``table_added``: column NULL, before NULL on the projection row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="new_table",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"row_count_estimate": 0},
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            source_id="src-1",
            table_id="new_table",
            column=None,
            drift_kind="table_added",
            before=None,
            after={"row_count_estimate": 0},
            strategy="table_set",
            reasoning="table appears in current snapshot",
            confidence=0.92,
            evidence={"before_tables": [], "after_tables": ["new_table"]},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_drifts) == 1
    row = proj.catalog_drifts[0]
    assert row["column"] is None
    assert row["before"] is None
    assert row["after"] == {"row_count_estimate": 0}
    assert row["drift_kind"] == "table_added"


@pytest.mark.asyncio
async def test_catalog_drift_acknowledged_advances_state(
    test_database_url: str,
) -> None:
    """proposed → acknowledged: state advances; acknowledger UUID + ts
    recorded. No downstream pipeline trigger, no cross-axis effect."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="email",
        drift_kind="column_added",
        before=None,
        after={"type": "varchar"},
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="email",
            drift_kind="column_added",
            before=None,
            after={"type": "varchar"},
            strategy="column_set",
        )
        await _emit_acknowledged(
            session,
            company_id=company_id,
            drift_id=drift_id,
            acknowledged_by_person_id="person-alice",
            notes="known schema migration",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_drifts) == 1
    row = proj.catalog_drifts[0]
    assert row["state"] == "acknowledged"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_catalog_drift_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + ts recorded.

    Uses the L2-specific 5th reason ``expected_change`` (distinct from
    L1's ``duplicate``, L8's ``wrong_pairing``, L6's ``wrong_level``,
    L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="t1",
        column="legacy",
        drift_kind="column_removed",
        before={"type": "int"},
        after=None,
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            source_id="src-1",
            table_id="t1",
            column="legacy",
            drift_kind="column_removed",
            before={"type": "int"},
            after=None,
            strategy="column_set",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            drift_id=drift_id,
            rejected_by_person_id="person-bob",
            reason="expected_change",
            notes="dropped per Q3 cleanup",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.catalog_drifts) == 1
    row = proj.catalog_drifts[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_drift_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal updates evidence + confidence + reasoning + strategy
    + before/after (the latest strategy's view). State stays "proposed"
    because no acknowledge/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    # NOTE: same args → same drift_id (deterministic dedup).
    drift_id = make_drift_id(
        source_id="src-1",
        table_id="customers",
        column="email",
        drift_kind="column_type_changed",
        before={"type": "varchar(255)"},
        after={"type": "text"},
    )

    async with session_scope(engine) as session:
        # First proposal — weak signal.
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            source_id="src-1",
            table_id="customers",
            column="email",
            drift_kind="column_type_changed",
            before={"type": "varchar(255)"},
            after={"type": "text"},
            strategy="column_type",
            reasoning="initial inference",
            confidence=0.85,
            evidence={"v": 1},
        )
        # Second proposal — refined evidence.
        await _emit_proposed(
            session,
            company_id=company_id,
            drift_id=drift_id,
            source_id="src-1",
            table_id="customers",
            column="email",
            drift_kind="column_type_changed",
            before={"type": "varchar(255)"},
            after={"type": "text"},
            strategy="column_type",
            reasoning="refined after second scan",
            confidence=0.95,
            evidence={"v": 2, "before_type": "varchar(255)", "after_type": "text"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.catalog_drifts) == 1
    row = proj.catalog_drifts[0]
    # The LATER proposal's fields win (forward-only update).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["reasoning"] == "refined after second scan"
    assert row["evidence"] == {
        "v": 2,
        "before_type": "varchar(255)",
        "after_type": "text",
    }
    # State remains proposed — no acknowledge/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown drift_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acknowledged_for_unknown_drift_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``catalog_drift_acknowledged`` with no prior proposal logs a
    warning and skips — the fold doesn't fabricate a row from
    incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the acknowledge.
        await _emit_acknowledged(
            session,
            company_id=company_id,
            drift_id="ghost-drift",
            acknowledged_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan ack.
    assert proj.catalog_drifts == []
    # A warning records the orphan for the operator surface.
    assert any(
        "catalog_drift_acknowledged" in r.message
        and "ghost-drift" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_drift_id_is_skipped(
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
            drift_id="ghost-drift-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.catalog_drifts == []
    assert any(
        "catalog_drift_rejected" in r.message
        and "ghost-drift-2" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_drifts_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's drifts do not leak into tenant B's fold."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical drift_id used in both tenants — composite PK
    # (company_id, drift_id) keeps them disjoint.
    drift_id = make_drift_id(
        source_id="src-shared",
        table_id="shared_table",
        column=None,
        drift_kind="table_added",
        before=None,
        after={"row_count_estimate": 0},
    )

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, drift_id=drift_id,
            source_id="src-shared", table_id="shared_table", column=None,
            drift_kind="table_added", before=None,
            after={"row_count_estimate": 0},
            strategy="table_set",
            reasoning="tenant A's reasoning",
            evidence={"a": 1},
        )
        await _emit_proposed(
            session, company_id=company_b, drift_id=drift_id,
            source_id="src-shared", table_id="shared_table", column=None,
            drift_kind="table_added", before=None,
            after={"row_count_estimate": 0},
            strategy="table_set",
            reasoning="tenant B's reasoning",
            evidence={"b": 1},
        )
        await _emit_acknowledged(
            session, company_id=company_a, drift_id=drift_id,
            acknowledged_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.catalog_drifts) == 1
    assert proj_a.catalog_drifts[0]["company_id"] == str(company_a)
    assert proj_a.catalog_drifts[0]["state"] == "acknowledged"
    assert proj_a.catalog_drifts[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.catalog_drifts) == 1
    assert proj_b.catalog_drifts[0]["company_id"] == str(company_b)
    # Tenant B never received the acknowledge — stays proposed.
    assert proj_b.catalog_drifts[0]["state"] == "proposed"
    assert proj_b.catalog_drifts[0]["reasoning"] == "tenant B's reasoning"
