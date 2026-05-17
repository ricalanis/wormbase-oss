"""Projection-fold tests for L7 Sub-wave A quality-check entries.

The /lake/quality dashboard surface (Sub-wave D) reads
``projection_quality_checks`` — one row per (company_id, check_id) pair
folded from three ledger entry kinds:

* ``quality_check_proposed`` → INSERT (or UPDATE evidence on
  re-proposal of the same check before resolution)
* ``quality_check_confirmed`` → UPDATE state = "confirmed"
* ``quality_check_rejected`` → UPDATE state = "rejected"

These tests pin:

* A single ``quality_check_proposed`` PEVR creates one projection row
  in state ``proposed`` with all inference fields preserved.
* A subsequent ``quality_check_confirmed`` advances state to
  ``confirmed`` + records the approving Person UUID + ts.
* A subsequent ``quality_check_rejected`` advances state to
  ``rejected`` + records the rejecting Person UUID + ts.
* Two ``quality_check_proposed`` entries for the same check_id collapse
  onto one row; the LATER proposal's evidence + confidence + strategy
  win (forward-only update; state stays "proposed").
* A confirm/reject for an UNKNOWN check_id (no prior proposal in the
  fold's scope) is logged + skipped — no row materialised.
* A forward-only state cycle (proposed → confirmed → rejected →
  confirmed) lands the final state on the projection row.
* Tenant isolation: rows scoped to company_id; tenant A's checks do
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
    check_id: str,
    table_id: str = "src-1.public.orders",
    column: str | None = "customer_id",
    check_kind: str = "not_null",
    config: dict | None = None,
    confidence: float = 0.95,
    strategy: str = "historical_stats",
    reasoning: str = "99.8% non-null observed",
    evidence: dict | None = None,
) -> None:
    """Emit a canonical ``quality_check_proposed`` PEVR cycle."""
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "quality_check_proposed",
            "ref_id": str(uuid4()),
            "reason": "inference strategy proposed check",
            "proposed_by": "agent-l7-axis",
        },
        execute_fn=lambda: {
            "tool": "emit_quality_check_proposed",
            "args": {
                "check_id": check_id,
                "table_id": table_id,
                "column": column,
                "check_kind": check_kind,
                "config": config if config is not None else {"threshold": 0.99},
                "confidence": confidence,
                "strategy": strategy,
                "reasoning": reasoning,
                "evidence": evidence if evidence is not None else {"k": "v"},
            },
            "result_ref": check_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_confirmed(
    session,
    *,
    company_id,
    check_id: str,
    confirmed_by_person_id: str = "person-uuid-admin",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``quality_check_confirmed`` PEVR cycle."""
    args = {
        "check_id": check_id,
        "confirmed_by_person_id": confirmed_by_person_id,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "quality_check_confirmed",
            "ref_id": str(uuid4()),
            "reason": "admin approved check",
            "proposed_by": confirmed_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_quality_check_confirmed",
            "args": args,
            "result_ref": check_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


async def _emit_rejected(
    session,
    *,
    company_id,
    check_id: str,
    rejected_by_person_id: str = "person-uuid-admin",
    reason: str = "false_positive",
    notes: str | None = None,
) -> None:
    """Emit a canonical ``quality_check_rejected`` PEVR cycle."""
    args = {
        "check_id": check_id,
        "rejected_by_person_id": rejected_by_person_id,
        "reason": reason,
    }
    if notes is not None:
        args["notes"] = notes
    await write_primitive(
        session,
        company_id=company_id,
        propose={
            "target_kind": "quality_check_rejected",
            "ref_id": str(uuid4()),
            "reason": f"admin rejected check ({reason})",
            "proposed_by": rejected_by_person_id,
        },
        execute_fn=lambda: {
            "tool": "emit_quality_check_rejected",
            "args": args,
            "result_ref": check_id,
        },
        verify_fn=_verify_pass,
        resolve_fn=_resolve_keep,
    )


# ---------------------------------------------------------------------------
# Single-entry folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_check_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``quality_check_proposed`` PEVR → one row (state=proposed)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    check_id = "check-abc-123"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_id, check_id=check_id,
            evidence={"non_null_ratio": 0.998, "sampled_n": 10000},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.quality_checks) == 1
    row = proj.quality_checks[0]
    assert row["company_id"] == str(company_id)
    assert row["check_id"] == check_id
    assert row["table_id"] == "src-1.public.orders"
    assert row["column"] == "customer_id"
    assert row["check_kind"] == "not_null"
    assert row["config"] == {"threshold": 0.99}
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "historical_stats"
    assert row["reasoning"] == "99.8% non-null observed"
    assert row["evidence"] == {"non_null_ratio": 0.998, "sampled_n": 10000}
    assert row["state"] == "proposed"
    assert row["state_changed_by"] is None
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_quality_check_confirmed_advances_state(
    test_database_url: str,
) -> None:
    """proposed → confirmed: state advances; approver UUID + ts recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    check_id = "check-confirmable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, check_id=check_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            check_id=check_id,
            confirmed_by_person_id="person-alice",
            notes="verified via staging",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.quality_checks) == 1
    row = proj.quality_checks[0]
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-alice"
    assert row["state_changed_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_quality_check_rejected_advances_state(
    test_database_url: str,
) -> None:
    """proposed → rejected: state advances; rejector UUID + reason recorded."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    check_id = "check-rejectable"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, check_id=check_id)
        await _emit_rejected(
            session,
            company_id=company_id,
            check_id=check_id,
            rejected_by_person_id="person-bob",
            reason="false_positive",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.quality_checks) == 1
    row = proj.quality_checks[0]
    assert row["state"] == "rejected"
    assert row["state_changed_by"] == "person-bob"


# ---------------------------------------------------------------------------
# Multi-proposal fold semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proposals_for_same_check_id_update_evidence(
    test_database_url: str,
) -> None:
    """Re-proposal (e.g. from a different strategy) updates evidence +
    confidence + strategy + reasoning + config. State stays "proposed"
    because no confirm/reject has landed."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    check_id = "check-multi-strategy"

    async with session_scope(engine) as session:
        # First proposal — schema_pattern with low confidence.
        await _emit_proposed(
            session,
            company_id=company_id,
            check_id=check_id,
            confidence=0.6,
            strategy="schema_pattern",
            reasoning="column name matches PK convention",
            config={"threshold": 0.95},
            evidence={"name_match": "id"},
        )
        # Second proposal — historical_stats with high confidence (the
        # composite service deduped onto the same check_id; the later
        # observation wins).
        await _emit_proposed(
            session,
            company_id=company_id,
            check_id=check_id,
            confidence=0.95,
            strategy="historical_stats",
            reasoning="100% non-null across 50K observed rows",
            config={"threshold": 1.0},
            evidence={"non_null_ratio": 1.0, "sampled_n": 50000},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # One row regardless of two proposals (composite PK collapses them).
    assert len(proj.quality_checks) == 1
    row = proj.quality_checks[0]
    # The LATER proposal's fields win (forward-only update; the row
    # surfaces the inference field the operator should see today).
    assert row["confidence"] == pytest.approx(0.95)
    assert row["strategy"] == "historical_stats"
    assert row["reasoning"] == "100% non-null across 50K observed rows"
    assert row["config"] == {"threshold": 1.0}
    assert row["evidence"] == {"non_null_ratio": 1.0, "sampled_n": 50000}
    # State remains proposed — no confirm/reject yet.
    assert row["state"] == "proposed"


# ---------------------------------------------------------------------------
# Defensive folds: unknown check_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_for_unknown_check_id_is_skipped(
    test_database_url: str,
    caplog,
) -> None:
    """A ``quality_check_confirmed`` with no prior proposal logs a warning
    and skips — the fold doesn't fabricate a row from incomplete signal."""
    import logging
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        # Skip the proposed step entirely — fire only the confirm.
        await _emit_confirmed(
            session,
            company_id=company_id,
            check_id="check-ghost",
            confirmed_by_person_id="person-x",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    # No row materialised — the fold short-circuits the orphan confirm.
    assert proj.quality_checks == []
    # A warning records the orphan for the operator surface.
    assert any(
        "quality_check_confirmed" in r.message and "check-ghost" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_rejected_for_unknown_check_id_is_skipped(
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
            check_id="check-ghost-2",
            reason="false_positive",
        )

    with caplog.at_level(logging.WARNING):
        async with session_scope(engine) as session:
            proj = await build_projections(session, company_id)

    assert proj.quality_checks == []
    assert any(
        "quality_check_rejected" in r.message and "check-ghost-2" in r.message
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
    check_id = "check-flip-flop"

    async with session_scope(engine) as session:
        await _emit_proposed(session, company_id=company_id, check_id=check_id)
        await _emit_confirmed(
            session,
            company_id=company_id,
            check_id=check_id,
            confirmed_by_person_id="person-1",
        )
        await _emit_rejected(
            session,
            company_id=company_id,
            check_id=check_id,
            rejected_by_person_id="person-2",
            reason="wrong_threshold",
        )
        await _emit_confirmed(
            session,
            company_id=company_id,
            check_id=check_id,
            confirmed_by_person_id="person-3",
            notes="re-validated after data refresh",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.quality_checks) == 1
    row = proj.quality_checks[0]
    # Final state is the LATEST forward-only write.
    assert row["state"] == "confirmed"
    assert row["state_changed_by"] == "person-3"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_checks_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Tenant A's checks do not leak into tenant B's fold (and vice versa)."""
    engine = get_engine(test_database_url)
    company_a = uuid4()
    company_b = uuid4()

    # Same logical check_id used in both tenants — composite PK
    # (company_id, check_id) keeps them disjoint.
    check_id = "check-shared-name"

    async with session_scope(engine) as session:
        await _emit_proposed(
            session, company_id=company_a, check_id=check_id,
            reasoning="tenant A's reasoning",
        )
        await _emit_proposed(
            session, company_id=company_b, check_id=check_id,
            reasoning="tenant B's reasoning",
        )
        await _emit_confirmed(
            session, company_id=company_a, check_id=check_id,
            confirmed_by_person_id="person-a-admin",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_a)
        proj_b = await build_projections(session, company_b)

    assert len(proj_a.quality_checks) == 1
    assert proj_a.quality_checks[0]["company_id"] == str(company_a)
    assert proj_a.quality_checks[0]["state"] == "confirmed"
    assert proj_a.quality_checks[0]["reasoning"] == "tenant A's reasoning"

    assert len(proj_b.quality_checks) == 1
    assert proj_b.quality_checks[0]["company_id"] == str(company_b)
    # Tenant B never received the confirm — stays proposed.
    assert proj_b.quality_checks[0]["state"] == "proposed"
    assert proj_b.quality_checks[0]["reasoning"] == "tenant B's reasoning"
