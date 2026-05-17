"""Projection-fold tests for ``topic_proposed`` → ``projection_topics``.

Phase 2 Task 2B: ``TopicSynthesisReactivity`` writes a PEVR cycle whose
``execute`` payload carries ``tool="emit_topic_proposed"`` + the
``TopicProposedPayload`` body. The projection builder folds those
entries into a per-(tenant, topic_id) row; re-emitting a growing
cluster (same topic_id, larger cluster_size) updates the row in place.

The /topics dashboard tab (Phase 3) reads ``projection_topics``;
this test pins the fold contract that the future tab depends on.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _emit_topic_args(
    *,
    topic_id: UUID,
    label: str,
    cluster_signature: str,
    cluster_size: int,
    member_message_ids: list[str],
    first_seen_at: datetime,
    last_seen_at: datetime,
    confidence: float = 0.78,
    served_by: str = "gemma",
) -> dict[str, object]:
    """Build the canonical execute-payload args body for emit_topic_proposed."""
    return {
        "topic_id": str(topic_id),
        "label": label,
        "cluster_signature": cluster_signature,
        "cluster_size": cluster_size,
        "member_message_ids": member_message_ids,
        "first_seen_at": first_seen_at.isoformat(),
        "last_seen_at": last_seen_at.isoformat(),
        "confidence": confidence,
        "served_by": served_by,
    }


@pytest.mark.asyncio
async def test_topic_proposed_creates_projection_row(
    test_database_url: str,
) -> None:
    """One ``topic_proposed`` ledger entry → one ``projection_topics`` row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    topic_id = uuid4()
    first_seen = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    last_seen = datetime(2026, 5, 3, 14, 30, tzinfo=UTC)

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "topic_proposed",
                "ref_id": str(topic_id),
                "reason": "topic_synthesis: cluster_size=4",
                "proposed_by": "process_extractor",
            },
            execute_fn=lambda: {
                "tool": "emit_topic_proposed",
                "args": _emit_topic_args(
                    topic_id=topic_id,
                    label="Q3 finance reporting",
                    cluster_signature="q3 finance reporting cadence weekly",
                    cluster_size=4,
                    member_message_ids=["M-001", "M-002", "M-003", "M-004"],
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                ),
                "result_ref": str(topic_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.topics) == 1
    row = proj.topics[0]
    assert row["topic_id"] == topic_id
    assert row["label"] == "Q3 finance reporting"
    assert row["cluster_size"] == 4
    assert row["served_by"] == "gemma"
    assert row["confidence"] == "0.78"  # str-stored for byte stability
    assert row["member_message_ids"] == ["M-001", "M-002", "M-003", "M-004"]


@pytest.mark.asyncio
async def test_topic_proposed_re_emit_updates_row_in_place(
    test_database_url: str,
) -> None:
    """Re-emit on a growing cluster updates the same row (same topic_id)."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    topic_id = uuid4()  # same id across two writes
    first_seen = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)

    # First emit: cluster_size=2
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "topic_proposed",
                "ref_id": str(topic_id),
                "reason": "topic_synthesis: cluster_size=2",
                "proposed_by": "process_extractor",
            },
            execute_fn=lambda: {
                "tool": "emit_topic_proposed",
                "args": _emit_topic_args(
                    topic_id=topic_id,
                    label="ad-hoc cluster",
                    cluster_signature="canonical text",
                    cluster_size=2,
                    member_message_ids=["M-001", "M-002"],
                    first_seen_at=first_seen,
                    last_seen_at=first_seen,
                    confidence=0.50,
                    served_by="heuristic",
                ),
                "result_ref": str(topic_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )

    # Second emit: cluster_size=5 with router-blessed label
    last_seen2 = datetime(2026, 5, 3, 16, 0, tzinfo=UTC)
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "topic_proposed",
                "ref_id": str(topic_id),
                "reason": "topic_synthesis: cluster_size=5",
                "proposed_by": "process_extractor",
            },
            execute_fn=lambda: {
                "tool": "emit_topic_proposed",
                "args": _emit_topic_args(
                    topic_id=topic_id,
                    label="canonical text → labeled",
                    cluster_signature="canonical text",
                    cluster_size=5,
                    member_message_ids=[
                        "M-001", "M-002", "M-003", "M-004", "M-005",
                    ],
                    first_seen_at=first_seen,
                    last_seen_at=last_seen2,
                    confidence=0.85,
                    served_by="gemma",
                ),
                "result_ref": str(topic_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Still exactly one row — same topic_id keys it.
    assert len(proj.topics) == 1
    row = proj.topics[0]
    assert row["topic_id"] == topic_id
    # Latest fields win.
    assert row["cluster_size"] == 5
    assert row["label"] == "canonical text → labeled"
    assert row["confidence"] == "0.85"
    assert row["served_by"] == "gemma"
    assert row["last_seen_at"] == last_seen2
    # first_seen_at stays at the original timestamp.
    assert row["first_seen_at"] == first_seen


@pytest.mark.asyncio
async def test_topics_projection_is_tenant_scoped(
    test_database_url: str,
) -> None:
    """Topics in tenant A are not visible from tenant B's projection fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    topic_id = uuid4()
    ts = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=tenant_a,
            propose={
                "target_kind": "topic_proposed",
                "ref_id": str(topic_id),
                "reason": "tenant A topic",
                "proposed_by": "process_extractor",
            },
            execute_fn=lambda: {
                "tool": "emit_topic_proposed",
                "args": _emit_topic_args(
                    topic_id=topic_id,
                    label="tenant A label",
                    cluster_signature="A signature",
                    cluster_size=2,
                    member_message_ids=["M-A1", "M-A2"],
                    first_seen_at=ts,
                    last_seen_at=ts,
                ),
                "result_ref": str(topic_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="passive_probabilistic",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.topics) == 1
    assert len(proj_b.topics) == 0
