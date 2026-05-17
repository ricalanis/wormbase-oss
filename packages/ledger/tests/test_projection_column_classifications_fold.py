"""Projection-fold tests for L6 Sub-wave A column-classification entries.

The /lake/column-classification dashboard surface (Sub-wave D) reads
``projection_column_classifications`` — one row per (company_id,
classification_id) pair folded from three ledger entry kinds:

* ``column_classification_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same classification before resolution)
* ``column_classification_confirmed`` → UPDATE state = "confirmed"
* ``column_classification_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``column_classification_proposed`` PEVR creates one
  projection row in state ``proposed`` with all inference fields
  preserved, including the cross-axis ``upstream_semantic_type_id``.
* A subsequent ``column_classification_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``column_classification_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts (uses the
  L6-specific ``wrong_level`` reason).
* Two ``column_classification_proposed`` entries for the same
  classification_id collapse onto one row; the LATER proposal's
  evidence + confidence + strategy + upstream link win (forward-only
  update; state stays "proposed").
* A confirm/reject for an UNKNOWN classification_id (no prior
  proposal in the fold's scope) is logged + skipped — no row
  materialised.
* Tenant isolation: rows scoped to company_id; tenant A's
  classifications do not leak into tenant B's fold.
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
    classification_id: str,
    table_id: str = "warehouse.dim_users",
    column: str = "ssn",
    classification_level: str = "regulated",
    upstream_semantic_type_id: str | None = "type-pii-ssn-1",
    confidence: float = 0.95,
    strategy: str = "semantic_type",
    reasoning: str = (
        "L5 confirmed semantic type pii_ssn → governance regulated"
    ),
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``column_classification_proposed`` PEVR cycle."""
    args = {
        "classification_id": classification_id,
        "table_id": table_id,
        "column": column,
        "classification_level": classification_level,
        "confidence": confidence,
        "strategy": strategy,
        "reasoning": reasoning,
        "evidence": evidence if evidence is not None else {"k": "v"},
    }
    if upstream_semantic_type_id is not None:
        args["upstream_semantic_type_id"] = upstream_semantic_type_id
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "column_classification_proposed",
            "ref_id": str(uuid4()),
            "reason": "L6 strategy proposed column classification",
            "proposed_by": "agent-l6-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_proposed",
            "args": args,
            "result_ref": classification_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    classification_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``column_classification_confirmed`` PEVR cycle."""
    args = {
        "classification_id": classification_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "column_classification_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved column classification",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_confirmed",
            "args": args,
            "result_ref": classification_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    classification_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "wrong_level",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``column_classification_rejected`` PEVR cycle."""
    args = {
        "classification_id": classification_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "column_classification_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected column classification ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_rejected",
            "args": args,
            "result_ref": classification_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_classification_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``column_classification_proposed`` PEVR → one row
    (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    classification_id = "cls-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, classification_id=classification_id,
            evidence={
                "upstream_semantic_type": "pii_ssn",
                "upstream_confidence": 0.97,
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.column_classifications) == 1
    row = proj.column_classifications[0]
    assert row["company_id"] == str(company_id)
    assert row["classification_id"] == classification_id
    assert row["table_id"] == "warehouse.dim_users"
    assert row["column"] == "ssn"
    assert row["classification_level"] == "regulated"
    assert row["upstream_semantic_type_id"] == "type-pii-ssn-1"
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "semantic_type"
    assert row["reasoning"] == (
        "L5 confirmed semantic type pii_ssn → governance regulated"
    )
    assert row["evidence"] == {
        "upstream_semantic_type": "pii_ssn",
        "upstream_confidence": 0.97,
    }
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_column_classification_proposed_naming_pattern_no_upstream(
    test_database_url: str,
) -> None:
    """``naming_pattern`` strategy → no L5 dependency, upstream NULL."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    classification_id = "cls-naming-1"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            classification_id=classification_id,
            column="api_secret",
            classification_level="confidential",
            upstream_semantic_type_id=None,
            confidence=0.92,
            strategy="naming_pattern",
            reasoning="column name matches /_secret$/ pattern",
            evidence={"regex": "_secret$"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.column_classifications) == 1
    row = proj.column_classifications[0]
    assert row["upstream_semantic_type_id"] is None
    assert row["strategy"] == "naming_pattern"
    assert row["classification_level"] == "confidential"


@pytest.mark.asyncio
async def test_column_classification_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    classification_id = "cls-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, classification_id=classification_id,
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            classification_id=classification_id,
            confirmed_by_person_id="person-alice",
            notes="verified regulated SSN column",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.column_classifications) == 1
    row = proj.column_classifications[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_column_classification_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded.

    Uses the L6-specific 5th reason ``wrong_level`` (distinct from
    L5's ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    classification_id = "cls-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, classification_id=classification_id,
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            classification_id=classification_id,
            rejected_by_person_id="person-bob",
            reason="wrong_level",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.column_classifications) == 1
    row = proj.column_classifications[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_classification_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a stronger strategy) updates evidence +
    confidence + strategy + reasoning + upstream link. State stays
    "proposed" because no confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    classification_id = "cls-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — naming_pattern with no upstream.
        await _emit_proposed(
            session,
            company_id=company_id,
            classification_id=classification_id,
            classification_level="pii",
            upstream_semantic_type_id=None,
            confidence=0.65,
            strategy="naming_pattern",
            reasoning="column name suggests PII",
            evidence={"regex": "(?i)ssn"},
        )
        # Second proposal — semantic_type with stronger confidence
        # AND cross-axis upstream link.
        await _emit_proposed(
            session,
            company_id=company_id,
            classification_id=classification_id,
            classification_level="regulated",
            upstream_semantic_type_id="type-pii-ssn-canonical",
            confidence=0.97,
            strategy="semantic_type",
            reasoning="L5 confirmed semantic type pii_ssn → regulated",
            evidence={"upstream_semantic_type": "pii_ssn"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.column_classifications) == 1
    row = proj.column_classifications[0]
    # The LATER proposal's fields win (forward-only update).
    assert row["confidence"] == pytest.approx(0.97)
    assert row["strategy"] == "semantic_type"
    assert row["classification_level"] == "regulated"
    assert row["upstream_semantic_type_id"] == "type-pii-ssn-canonical"
    assert row["reasoning"] == (
        "L5 confirmed semantic type pii_ssn → regulated"
    )
    assert row["evidence"] == {"upstream_semantic_type": "pii_ssn"}
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown classification_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_classification_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``column_classification_confirmed`` with no prior proposal logs
    a warning and skips — the fold doesn't fabricate a row from
    incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            classification_id="cls-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.column_classifications == []
    # A warning records the orphan for the operator surface.
    assert any(
        "column_classification_confirmed" in r.message
        and "cls-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_classification_id_is_skipped(
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
            classification_id="cls-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.column_classifications == []
    assert any(
        "column_classification_rejected" in r.message
        and "cls-ghost-2" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_classifications_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's classifications do not leak into tenant B's fold."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical classification_id used in both tenants — composite PK
    # (company_id, classification_id) keeps them disjoint.
    classification_id = "cls-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, classification_id=classification_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, classification_id=classification_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, classification_id=classification_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.column_classifications) == 1
    assert proj_a.column_classifications[0]["company_id"] == str(company_a)
    assert proj_a.column_classifications[0]["state"] == "confirmed"
    assert proj_a.column_classifications[0]["reasoning"] == (
        "tenant A's reasoning"
    )

    assert len(proj_b.column_classifications) == 1
    assert proj_b.column_classifications[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.column_classifications[0]["state"] == "proposed"
    assert proj_b.column_classifications[0]["reasoning"] == (
        "tenant B's reasoning"
    )
