"""Projection-fold tests for §4.5 compounding-loop entries (Wave 3 Task 4).

The /lake/query-improvement dashboard surface reads two projection rows:

* ``projection_query_outcomes``  — one row per ``query_outcome_recorded``
  ledger execute entry. Embeddings live on the migration-defined column
  (dialect-aware Vector/JSON); the fold-side projection mirror omits
  them, so this test does NOT assert on the embedding column.
* ``projection_query_templates`` — one row per ``query_template_promoted``
  propose entry written by the OutcomeToTemplatePromotion W5a Reactivity.
  Note: this kind uses a typed-payload PEVR (no ``tool=emit_*`` envelope),
  so the fold detects by payload shape.

These tests pin:

* one ``query_outcome_recorded`` PEVR with ``tool=emit_query_outcome_recorded``
  + canonical payload → one row in ``projections.query_outcomes``
* outcome fields (quality_score, used, useful, user_correction,
  nl_question, agent_query_id, final_query_spec, result_summary,
  recorded_at) round-trip verbatim through the fold
* one ``query_template_promoted`` PEVR with payload-shape body
  (nl_intent + promoted_from_outcome_ids + query_spec at the envelope
  level, NOT under ``args``) → one row in ``projections.query_templates``
* template fields (domain_id, nl_intent, query_spec,
  promoted_from_outcome_ids, quality_score, hit_count=0) round-trip
* multi-phase template PEVR (propose+execute+verify+resolve all carry
  the same body) folds into ONE row — not four — keyed on the propose
  entry's UUID
* tenant isolation: rows for tenant A invisible from tenant B's fold

Note: ``query_correction_suggested`` has NO projection table at v016/v017,
so this test does NOT cover its fold. The correction suggestion only
surfaces through the recursive CTE in /trace/agent_query/[id] (Task 3),
not as a first-class projection table. If a future migration adds
``projection_query_corrections``, add coverage here.
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


# ---------------------------------------------------------------------------
# query_outcome_recorded — canonical PEVR with tool/args envelope.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_outcome_recorded_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``query_outcome_recorded`` PEVR → one row in ``projections.query_outcomes``."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_query_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": agent_query_id,
                "reason": "agent recorded outcome",
                "proposed_by": "agent-uuid-1",
            },
            execute_fn=lambda: {
                "tool": "emit_query_outcome_recorded",
                "args": {
                    "agent_query_id": agent_query_id,
                    "nl_question": "what was Q3 revenue?",
                    "final_query_spec": {
                        "metric": "revenue_total",
                        "time_grain": "quarter",
                    },
                    "result_summary": {"row_count": 1, "preview": "$1.2M"},
                    "used": True,
                    "useful": True,
                    "user_correction": None,
                    "quality_score": "1.0",
                },
                "result_ref": agent_query_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.query_outcomes) == 1
    row = proj.query_outcomes[0]
    assert row["company_id"] == str(company_id)
    assert row["agent_query_id"] == agent_query_id
    assert row["nl_question"] == "what was Q3 revenue?"
    assert row["final_query_spec"] == {
        "metric": "revenue_total",
        "time_grain": "quarter",
    }
    assert row["result_summary"] == {"row_count": 1, "preview": "$1.2M"}
    assert row["used"] is True
    assert row["useful"] is True
    assert row["user_correction"] is None
    assert row["quality_score"] == "1.0"
    # ``recorded_at`` is the entry ts; just assert tz-aware.
    assert row["recorded_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_query_outcome_recorded_carries_user_correction(
    test_database_url: str,
) -> None:
    """A useful=False, used=True outcome with a user_correction string
    folds verbatim — the correction lands on the projection row, and
    quality_score is a low-but-nonzero number."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_query_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": agent_query_id,
                "reason": "agent recorded outcome with correction",
                "proposed_by": "agent-uuid-1",
            },
            execute_fn=lambda: {
                "tool": "emit_query_outcome_recorded",
                "args": {
                    "agent_query_id": agent_query_id,
                    "nl_question": "what was last month's churn?",
                    "final_query_spec": {"metric": "churn_rate"},
                    "result_summary": {"value": 0.034},
                    "used": True,
                    "useful": False,
                    "user_correction": "wrong metric — wanted gross churn",
                    "quality_score": "0.2",
                },
                "result_ref": agent_query_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.query_outcomes) == 1
    row = proj.query_outcomes[0]
    assert row["used"] is True
    assert row["useful"] is False
    assert row["user_correction"] == "wrong metric — wanted gross churn"
    assert row["quality_score"] == "0.2"


# ---------------------------------------------------------------------------
# v2.B Phase 3b — embedding field folds verbatim onto the projection row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_outcome_recorded_with_embedding_folds_verbatim(
    test_database_url: str,
) -> None:
    """A query_outcome_recorded with a 768-dim embedding on the payload
    lands as a list[float] on the projection row (write-once contract)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_query_id = str(uuid4())
    embedding = [0.001 * i for i in range(768)]

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": agent_query_id,
                "reason": "outcome with embedding",
                "proposed_by": "agent-uuid-1",
            },
            execute_fn=lambda: {
                "tool": "emit_query_outcome_recorded",
                "args": {
                    "agent_query_id": agent_query_id,
                    "nl_question": "what is revenue this quarter?",
                    "final_query_spec": {"metric": "revenue_total"},
                    "result_summary": {"row_count": 1},
                    "used": True,
                    "useful": True,
                    "user_correction": None,
                    "quality_score": "0.95",
                    "embedding": embedding,
                },
                "result_ref": agent_query_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.query_outcomes) == 1
    row = proj.query_outcomes[0]
    assert row["embedding"] is not None
    assert len(row["embedding"]) == 768
    # Values preserved (allowing for float-to-float conversion).
    assert row["embedding"][0] == pytest.approx(0.0)
    assert row["embedding"][100] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_query_outcome_recorded_without_embedding_folds_as_none(
    test_database_url: str,
) -> None:
    """Pre-Phase-3b entries (no embedding field) fold with embedding=None;
    the substring-fallback clustering path stays valid."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    agent_query_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": agent_query_id,
                "reason": "outcome no embedding",
                "proposed_by": "agent-uuid-1",
            },
            execute_fn=lambda: {
                "tool": "emit_query_outcome_recorded",
                "args": {
                    "agent_query_id": agent_query_id,
                    "nl_question": "no embedding here",
                    "final_query_spec": {},
                    "result_summary": {},
                    "used": True,
                    "useful": True,
                    "user_correction": None,
                    "quality_score": "0.95",
                    # No embedding key at all — pre-Phase-3b shape.
                },
                "result_ref": agent_query_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.query_outcomes) == 1
    assert proj.query_outcomes[0]["embedding"] is None


# ---------------------------------------------------------------------------
# query_template_promoted — typed-payload PEVR (no ``tool=emit_*``).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_template_promoted_creates_projection_row(
    test_database_url: str,
) -> None:
    """OutcomeToTemplatePromotion writes a typed-payload PEVR; one row in
    ``projections.query_templates`` lands per promotion."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    domain_id = str(uuid4())
    outcome_id_1 = str(uuid4())
    outcome_id_2 = str(uuid4())
    outcome_id_3 = str(uuid4())

    # The Reactivity passes the payload dict directly as ``propose``,
    # then ``dict(promotion_payload)`` for execute. All four phases
    # carry the same body.
    promotion_payload = {
        "domain_id": domain_id,
        "nl_intent": "revenue_by_quarter",
        "query_spec": {"metric": "revenue_total", "time_grain": "quarter"},
        "promoted_from_outcome_ids": [outcome_id_1, outcome_id_2, outcome_id_3],
        "quality_score": "0.9500",
    }

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose=dict(promotion_payload),
            execute_fn=lambda: dict(promotion_payload),
            verify_fn=lambda _r: {
                **promotion_payload,
                "checks": [{"name": "template_promoted", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                **promotion_payload,
                "outcome": "keep",
                "rationale": "cluster of 3 outcomes promoted to template",
            },
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Exactly ONE row even though all four phases carry the same body —
    # the fold anchors on the propose phase.
    assert len(proj.query_templates) == 1
    row = proj.query_templates[0]
    assert row["company_id"] == str(company_id)
    assert row["domain_id"] == domain_id
    assert row["nl_intent"] == "revenue_by_quarter"
    assert row["query_spec"] == {
        "metric": "revenue_total",
        "time_grain": "quarter",
    }
    # promoted_from_outcome_ids is preserved verbatim as a list.
    assert row["promoted_from_outcome_ids"] == [
        outcome_id_1,
        outcome_id_2,
        outcome_id_3,
    ]
    assert row["quality_score"] == "0.9500"
    # hit_count defaults to 0 — the query-cache path increments at read time.
    assert row["hit_count"] == 0
    assert row["promoted_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_query_template_promoted_is_idempotent_across_phases(
    test_database_url: str,
) -> None:
    """All four PEVR phases share the same payload body; the fold MUST
    produce one row (anchored on propose) — not four.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    promotion_payload = {
        "domain_id": str(uuid4()),
        "nl_intent": "active_users_dau",
        "query_spec": {"metric": "dau"},
        "promoted_from_outcome_ids": [str(uuid4()) for _ in range(3)],
        "quality_score": "0.9000",
    }

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose=dict(promotion_payload),
            execute_fn=lambda: dict(promotion_payload),
            verify_fn=lambda _r: {**promotion_payload, "passed": True},
            resolve_fn=lambda _v: {**promotion_payload, "outcome": "keep"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # The four-phase PEVR ≠ four rows. The propose-anchor contract
    # guarantees one row per cluster promotion.
    assert len(proj.query_templates) == 1


# ---------------------------------------------------------------------------
# Tenant scoping.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_outcomes_projection_is_tenant_scoped(
    test_database_url: str,
) -> None:
    """An outcome recorded in tenant A is invisible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    agent_query_id = str(uuid4())

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=tenant_a,
            propose={
                "target_kind": "query_outcome_recorded",
                "ref_id": agent_query_id,
                "reason": "tenant A outcome",
                "proposed_by": "agent-uuid-1",
            },
            execute_fn=lambda: {
                "tool": "emit_query_outcome_recorded",
                "args": {
                    "agent_query_id": agent_query_id,
                    "nl_question": "tenant-A question",
                    "final_query_spec": {},
                    "result_summary": {},
                    "used": False,
                    "useful": False,
                    "user_correction": None,
                    "quality_score": "0.0",
                },
                "result_ref": agent_query_id,
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.query_outcomes) == 1
    assert len(proj_b.query_outcomes) == 0


@pytest.mark.asyncio
async def test_query_templates_projection_is_tenant_scoped(
    test_database_url: str,
) -> None:
    """A template promoted in tenant A is invisible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    promotion_payload = {
        "domain_id": str(uuid4()),
        "nl_intent": "tenant-A intent",
        "query_spec": {"metric": "revenue_total"},
        "promoted_from_outcome_ids": [str(uuid4())],
        "quality_score": "0.9500",
    }

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=tenant_a,
            propose=dict(promotion_payload),
            execute_fn=lambda: dict(promotion_payload),
            verify_fn=lambda _r: {**promotion_payload, "passed": True},
            resolve_fn=lambda _v: {**promotion_payload, "outcome": "keep"},
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.query_templates) == 1
    assert len(proj_b.query_templates) == 0
