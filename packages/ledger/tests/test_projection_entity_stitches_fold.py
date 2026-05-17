"""Projection-fold tests for L8 Sub-wave A entity-stitch entries.

The /lake/entity-stitch dashboard surface (Sub-wave D) reads
``projection_entity_stitches`` — one row per (company_id, stitch_id)
pair folded from three ledger entry kinds:

* ``entity_stitch_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same stitch before resolution)
* ``entity_stitch_confirmed`` → UPDATE state = "confirmed"
* ``entity_stitch_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``entity_stitch_proposed`` PEVR creates one projection row
  in state ``proposed`` with all inference fields preserved,
  including the cross-axis ``upstream_semantic_type_id`` and both
  endpoint triples.
* A subsequent ``entity_stitch_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``entity_stitch_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts (uses the
  L8-specific ``wrong_pairing`` reason).
* Two ``entity_stitch_proposed`` entries for the same stitch_id
  collapse onto one row; the LATER proposal's evidence + confidence
  + strategy + entity_kind + upstream link win (forward-only
  update; state stays "proposed").
* A confirm/reject for an UNKNOWN stitch_id (no prior proposal in
  the fold's scope) is logged + skipped — no row materialised.
* Tenant isolation: rows scoped to company_id; tenant A's stitches
  do not leak into tenant B's fold.
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
    stitch_id: str,
    src_source_id_a: str = "src-stripe-1",
    src_table_a: str = "customers",
    src_column_a: str = "email",
    src_source_id_b: str = "src-salesforce-1",
    src_table_b: str = "contacts",
    src_column_b: str = "email",
    upstream_semantic_type_id: str | None = "type-pii-email-1",
    entity_kind: str = "person",
    confidence: float = 0.93,
    strategy: str = "sample_overlap",
    reasoning: str = (
        "87% of stripe.customers.email values found in salesforce.contacts.email"
    ),
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``entity_stitch_proposed`` PEVR cycle."""
    args = {
        "stitch_id": stitch_id,
        "src_source_id_a": src_source_id_a,
        "src_table_a": src_table_a,
        "src_column_a": src_column_a,
        "src_source_id_b": src_source_id_b,
        "src_table_b": src_table_b,
        "src_column_b": src_column_b,
        "entity_kind": entity_kind,
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
            "target_kind": "entity_stitch_proposed",
            "ref_id": str(uuid4()),
            "reason": "L8 strategy proposed cross-source entity stitch",
            "proposed_by": "agent-l8-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_entity_stitch_proposed",
            "args": args,
            "result_ref": stitch_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    stitch_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``entity_stitch_confirmed`` PEVR cycle."""
    args = {
        "stitch_id": stitch_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "entity_stitch_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved entity stitch",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_entity_stitch_confirmed",
            "args": args,
            "result_ref": stitch_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    stitch_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "wrong_pairing",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``entity_stitch_rejected`` PEVR cycle."""
    args = {
        "stitch_id": stitch_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "entity_stitch_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected entity stitch ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_entity_stitch_rejected",
            "args": args,
            "result_ref": stitch_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_stitch_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``entity_stitch_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    stitch_id = "stitch-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            evidence={
                "sample_overlap_pct": 0.87,
                "endpoints_sampled": 200,
                "upstream_semantic_type": "pii_email",
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.entity_stitches) == 1
    row = proj.entity_stitches[0]
    assert row["company_id"] == str(company_id)
    assert row["stitch_id"] == stitch_id
    assert row["src_source_id_a"] == "src-stripe-1"
    assert row["src_table_a"] == "customers"
    assert row["src_column_a"] == "email"
    assert row["src_source_id_b"] == "src-salesforce-1"
    assert row["src_table_b"] == "contacts"
    assert row["src_column_b"] == "email"
    assert row["upstream_semantic_type_id"] == "type-pii-email-1"
    assert row["entity_kind"] == "person"
    assert row["confidence"] == pytest.approx(0.93)
    assert row["strategy"] == "sample_overlap"
    assert row["reasoning"] == (
        "87% of stripe.customers.email values found in salesforce.contacts.email"
    )
    assert row["evidence"] == {
        "sample_overlap_pct": 0.87,
        "endpoints_sampled": 200,
        "upstream_semantic_type": "pii_email",
    }
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_entity_stitch_proposed_name_match_no_upstream(
    test_database_url: str,
) -> None:
    """``name_match`` strategy → no L5 dependency, upstream NULL."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    stitch_id = "stitch-name-1"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            src_column_a="customer_id",
            src_column_b="customer_id",
            upstream_semantic_type_id=None,
            confidence=0.78,
            strategy="name_match",
            reasoning="exact column-name match across sources",
            evidence={"name_match": "customer_id"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.entity_stitches) == 1
    row = proj.entity_stitches[0]
    assert row["upstream_semantic_type_id"] is None
    assert row["strategy"] == "name_match"


@pytest.mark.asyncio
async def test_entity_stitch_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    stitch_id = "stitch-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, stitch_id=stitch_id,
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            confirmed_by_person_id="person-alice",
            notes="verified the bridge",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.entity_stitches) == 1
    row = proj.entity_stitches[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_entity_stitch_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded.

    Uses the L8-specific 5th reason ``wrong_pairing`` (distinct from
    L6's ``wrong_level``, L5's ``wrong_type``, L4's
    ``already_handled`` and L7's ``wrong_threshold``)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    stitch_id = "stitch-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, stitch_id=stitch_id,
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            rejected_by_person_id="person-bob",
            reason="wrong_pairing",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.entity_stitches) == 1
    row = proj.entity_stitches[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_stitch_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a stronger strategy) updates evidence +
    confidence + strategy + reasoning + entity_kind + upstream link.
    State stays "proposed" because no confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    stitch_id = "stitch-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — name_match with no upstream.
        await _emit_proposed(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            entity_kind="other",
            upstream_semantic_type_id=None,
            confidence=0.62,
            strategy="name_match",
            reasoning="column-name match across sources",
            evidence={"name_match": "email"},
        )
        # Second proposal — sample_overlap with stronger confidence,
        # tightened entity_kind, AND cross-axis upstream link.
        await _emit_proposed(
            session,
            company_id=company_id,
            stitch_id=stitch_id,
            entity_kind="person",
            upstream_semantic_type_id="type-pii-email-canonical",
            confidence=0.95,
            strategy="sample_overlap",
            reasoning="92% sample overlap + L5 pii_email confirmation",
            evidence={
                "sample_overlap_pct": 0.92,
                "upstream_semantic_type": "pii_email",
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.entity_stitches) == 1
    row = proj.entity_stitches[0]
    # The LATER proposal's fields win (forward-only update).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "sample_overlap"
    assert row["entity_kind"] == "person"
    assert row["upstream_semantic_type_id"] == "type-pii-email-canonical"
    assert row["reasoning"] == (
        "92% sample overlap + L5 pii_email confirmation"
    )
    assert row["evidence"] == {
        "sample_overlap_pct": 0.92,
        "upstream_semantic_type": "pii_email",
    }
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown stitch_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_stitch_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``entity_stitch_confirmed`` with no prior proposal logs a
    warning and skips — the fold doesn't fabricate a row from
    incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            stitch_id="stitch-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.entity_stitches == []
    # A warning records the orphan for the operator surface.
    assert any(
        "entity_stitch_confirmed" in r.message
        and "stitch-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_stitch_id_is_skipped(
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
            stitch_id="stitch-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.entity_stitches == []
    assert any(
        "entity_stitch_rejected" in r.message
        and "stitch-ghost-2" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_stitches_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's stitches do not leak into tenant B's fold."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical stitch_id used in both tenants — composite PK
    # (company_id, stitch_id) keeps them disjoint.
    stitch_id = "stitch-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, stitch_id=stitch_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, stitch_id=stitch_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, stitch_id=stitch_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.entity_stitches) == 1
    assert proj_a.entity_stitches[0]["company_id"] == str(company_a)
    assert proj_a.entity_stitches[0]["state"] == "confirmed"
    assert proj_a.entity_stitches[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.entity_stitches) == 1
    assert proj_b.entity_stitches[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.entity_stitches[0]["state"] == "proposed"
    assert proj_b.entity_stitches[0]["reasoning"] == "tenant B's reasoning"
