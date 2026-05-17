"""Projection-fold tests for L5 Sub-wave A semantic-type entries.

The /lake/semantic-types dashboard surface (Sub-wave D) reads
``projection_semantic_types`` — one row per (company_id, type_id) pair
folded from three ledger entry kinds:

* ``semantic_type_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same type before resolution)
* ``semantic_type_confirmed`` → UPDATE state = "confirmed"
* ``semantic_type_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``semantic_type_proposed`` PEVR creates one projection row
  in state ``proposed`` with all inference fields preserved.
* A subsequent ``semantic_type_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``semantic_type_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts.
* Two ``semantic_type_proposed`` entries for the same type_id collapse
  onto one row; the LATER proposal's evidence + confidence + strategy
  win (forward-only update; state stays "proposed").
* A confirm/reject for an UNKNOWN type_id (no prior proposal in the
  fold's scope) is logged + skipped — no row materialised.
* A forward-only state cycle (proposed → confirmed → rejected →
  confirmed) lands the final state on the projection row.
* Tenant isolation: rows scoped to company_id; tenant A's types do
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
    type_id: str,
    table_id: str = "warehouse.dim_users",
    column: str = "contact_email",
    semantic_type: str = "email",
    confidence: float = 0.92,
    strategy: str = "value_pattern",
    reasoning: str = "value-pattern strategy matched RFC5322 regex",
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``semantic_type_proposed`` PEVR cycle."""
    args = {
        "type_id": type_id,
        "table_id": table_id,
        "column": column,
        "semantic_type": semantic_type,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": reasoning,
        "evidence": evidence if evidence is not None else {"k": "v"},
    }
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_proposed",
            "ref_id": str(uuid4()),
            "reason": "L5 strategy proposed semantic type",
            "proposed_by": "agent-l5-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_proposed",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    type_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``semantic_type_confirmed`` PEVR cycle."""
    args = {
        "type_id": type_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved semantic type",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_confirmed",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    type_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "false_positive",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``semantic_type_rejected`` PEVR cycle."""
    args = {
        "type_id": type_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "semantic_type_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected semantic type ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_rejected",
            "args": args,
            "result_ref": type_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_type_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``semantic_type_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    type_id = "type-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, type_id=type_id,
            evidence={"match_count": 18, "sample_n": 20},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.semantic_types) == 1
    row = proj.semantic_types[0]
    assert row["company_id"] == str(company_id)
    assert row["type_id"] == type_id
    assert row["table_id"] == "warehouse.dim_users"
    assert row["column"] == "contact_email"
    assert row["semantic_type"] == "email"
    assert row["confidence"] == pytest.approx(0.92)
    assert row["strategy"] == "value_pattern"
    assert row["reasoning"] == "value-pattern strategy matched RFC5322 regex"
    assert row["evidence"] == {"match_count": 18, "sample_n": 20}
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_semantic_type_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    type_id = "type-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, type_id=type_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            type_id=type_id,
            confirmed_by_person_id="person-alice",
            notes="verified email column",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.semantic_types) == 1
    row = proj.semantic_types[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_semantic_type_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded.

    Uses the L5-specific 5th reason ``wrong_type`` (replaces L4's
    ``already_handled`` and L7's ``wrong_threshold``)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    type_id = "type-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, type_id=type_id)
        await _emit_rejected(
            session,
            company_id=company_id,
            type_id=type_id,
            rejected_by_person_id="person-bob",
            reason="wrong_type",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.semantic_types) == 1
    row = proj.semantic_types[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_type_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a different strategy) updates evidence +
    confidence + strategy + reasoning + semantic_type. State stays
    "proposed" because no confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    type_id = "type-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — column_name with low confidence.
        await _emit_proposed(
            session,
            company_id=company_id,
            type_id=type_id,
            confidence=0.65,
            strategy="column_name",
            reasoning="column name suggests email",
            evidence={"regex": r"(?i)^email$"},
        )
        # Second proposal — value_pattern with high confidence.
        await _emit_proposed(
            session,
            company_id=company_id,
            type_id=type_id,
            confidence=0.95,
            strategy="value_pattern",
            reasoning="20/20 sampled values match RFC5322",
            evidence={"match_count": 20, "sample_n": 20},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.semantic_types) == 1
    row = proj.semantic_types[0]
    # The LATER proposal's fields win (forward-only update).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "value_pattern"
    assert row["reasoning"] == "20/20 sampled values match RFC5322"
    assert row["evidence"] == {"match_count": 20, "sample_n": 20}
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown type_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_type_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``semantic_type_confirmed`` with no prior proposal logs a warning
    and skips — the fold doesn't fabricate a row from incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            type_id="type-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.semantic_types == []
    # A warning records the orphan for the operator surface.
    assert any(
        "semantic_type_confirmed" in r.message and "type-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_type_id_is_skipped(
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
            type_id="type-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.semantic_types == []
    assert any(
        "semantic_type_rejected" in r.message and "type-ghost-2" in r.message
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
    type_id = "type-flip-flop"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, type_id=type_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            type_id=type_id,
            confirmed_by_person_id="person-1",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            type_id=type_id,
            rejected_by_person_id="person-2",
            reason="wrong_type",
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            type_id=type_id,
            confirmed_by_person_id="person-3",
            notes="re-validated after data refresh",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.semantic_types) == 1
    row = proj.semantic_types[0]
    # Final state is the LATEST forward-only write.
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-3"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_types_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's types do not leak into tenant B's fold (and vice versa)."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical type_id used in both tenants — composite PK
    # (company_id, type_id) keeps them disjoint.
    type_id = "type-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, type_id=type_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, type_id=type_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, type_id=type_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.semantic_types) == 1
    assert proj_a.semantic_types[0]["company_id"] == str(company_a)
    assert proj_a.semantic_types[0]["state"] == "confirmed"
    assert proj_a.semantic_types[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.semantic_types) == 1
    assert proj_b.semantic_types[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.semantic_types[0]["state"] == "proposed"
    assert proj_b.semantic_types[0]["reasoning"] == "tenant B's reasoning"
