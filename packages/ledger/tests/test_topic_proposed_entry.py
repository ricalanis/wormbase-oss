"""Round-trip + registration tests for ``TopicProposedPayload``.

Phase 2 Task 2B (Topic Synthesis Real Implementation):

* ``topic_proposed`` is the new entry kind emitted by ``TopicSynthesisReactivity``
  when a chat-cluster crosses the topic-promotion threshold.
* The kind is registered in ``KIND_REGISTRY`` / ``ALL_KINDS`` automatically
  via ``EntryPayload.__init_subclass__``.
* The payload round-trips through ``model_dump(mode="json") →
  model_validate``, so the downstream ``_emit_pevr`` execute-shape is
  byte-stable across replays.

The 80-kind threshold (Rule 5 raised to 100 by 2026-05-04 doctrine
addendum) is checked as a guardrail.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    TopicProposedPayload,
)


def test_topic_proposed_kind_registered() -> None:
    """``topic_proposed`` is in the registry + ALL_KINDS set."""
    assert "topic_proposed" in ALL_KINDS
    assert "topic_proposed" in KIND_REGISTRY
    assert KIND_REGISTRY["topic_proposed"] is TopicProposedPayload


def test_kind_registry_under_threshold() -> None:
    """Rule 5 threshold raised to 100 (2026-05-04 doctrine addendum).

    Wave H Phase 2 Task 2C's ``position_confirmed`` +
    ``position_rejected`` brought it to 82; the 2026-05-05
    ``conversation_sync`` lineage entry from the WhatsApp +
    conversation-provenance plan brought it to 83; the 2026-05-11
    Semantic Layer Wave 1 / Task 4 adds five ``external_*`` kinds
    (``external_catalog_imported``, ``external_catalog_drift_detected``,
    ``external_lineage_imported``, ``external_policy_imported``,
    ``external_metric_imported``) for catalog-mirror data plane,
    bringing it to 88. Semantic Layer Wave 2 / Task 1 (2026-05-11) then
    adds four agent-gateway core kinds (``agent_registered``,
    ``agent_grant``, ``agent_query``, ``credential``) per doctrine
    Addendum 3 — single-kind PEVR for ``agent_query``, status-field
    consolidation for ``agent_grant`` + ``credential`` — bringing it
    to 92. Wave 2 Task 3 (2026-05-11) then adds four §4.5
    compounding-loop kinds (``query_outcome_recorded``,
    ``query_correction_suggested``, ``query_template_promoted``,
    ``semantic_gap_proposed``) per doctrine Addendum 3 §B — outcomes
    and templates kept as separate kinds (NOT folded into
    ``agent_query.resolve``) because temporality and provenance
    differ — bringing it to 96. v2.B Phase 2 (2026-05-12) then adds
    three more compounding-loop kinds (``bad_pattern_proposed``,
    ``semantic_gap_escalated``, ``data_product_recommended``) per the
    same doctrine §B (compounding family budget has headroom under the
    raised 100-kind ceiling per Wave F Addendum 1) — bringing it to 99.
    v2.B Phase 3 (2026-05-12) adds ``clock_tick`` for the periodic-tick
    emitter that drives time-based Reactivities, bringing the total to
    100. v2.A Batch A (2026-05-12) adds three subscription kinds
    (``agent_subscription_created``, ``agent_subscription_revoked``,
    ``agent_event_delivered``) closing Seam #3 (agent-as-teammate),
    bringing the total to 103 — well under the 150-kind ceiling per
    Wave F Addendum 4. The check guards against silent drift.
    """
    assert len(ALL_KINDS) == 133, (
        f"expected exactly 133 entry kinds (88 Wave 1 + 4 agent-gateway + "
        f"4 compounding + 3 v2.B Phase 2 compounding axes + 1 clock_tick + "
        f"3 v2.A subscription kinds + 1 agent_metadata_updated + "
        f"1 tenant_quota_consumed + 1 tenant_engine_registered + "
        f"3 L3 Sub-wave A lineage_edge kinds + "
        f"2 Onboarding Sub-wave C kinds [domain_pack_selected + person_invited] + "
        f"3 L7 Sub-wave A quality_check kinds + "
        f"3 L4 Sub-wave A schema_impact kinds + "
        f"3 L5 Sub-wave A semantic_type kinds + "
        f"3 L6 Sub-wave A column_classification kinds + "
        f"3 L8 Sub-wave A entity_stitch kinds + "
        f"3 L1 Sub-wave A source_candidate kinds + "
        f"3 L2 Sub-wave A catalog_drift kinds [FINAL planned axis] + "
        f"1 catalog-mirror Wave 2 Sub-wave A substrate "
        f"[catalog_table_imported]); got "
        f"{len(ALL_KINDS)}"
    )


def test_topic_proposed_payload_round_trips_via_json() -> None:
    """A fully-populated payload survives ``model_dump → model_validate``.

    This is the canonical contract for any ledger-bound payload — the
    ``_emit_pevr`` helper hands ``model_dump(mode="json")`` to the
    ledger writer, which round-trips it through ``model_validate`` on
    replay.
    """
    payload = TopicProposedPayload(
        topic_id=uuid4(),
        label="Q3 finance reporting cadence",
        cluster_signature="q3 finance reporting cadence weekly",
        cluster_size=4,
        member_message_ids=["M-001", "M-002", "M-003", "M-004"],
        first_seen_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 5, 3, 14, 30, tzinfo=UTC),
        confidence=0.78,
        served_by="gemma",
    )
    dumped = payload.model_dump(mode="json")
    restored = TopicProposedPayload.model_validate(dumped)
    assert restored == payload


def test_topic_proposed_payload_optional_fields_default() -> None:
    """``served_by`` and ``confidence`` accept conservative defaults.

    A heuristic-only path (router unavailable) emits with
    ``served_by="heuristic"`` and ``confidence=0.5`` — the floor below
    which the dashboard should render a "needs review" badge.
    """
    payload = TopicProposedPayload(
        topic_id=uuid4(),
        label="ad-hoc cluster: short",
        cluster_signature="short",
        cluster_size=2,
        member_message_ids=["M-1", "M-2"],
        first_seen_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 5, 3, 10, 5, tzinfo=UTC),
    )
    assert payload.confidence == 0.5
    assert payload.served_by == "heuristic"


def test_topic_proposed_payload_rejects_naive_ts() -> None:
    """tz-naive datetimes are rejected (mirror policy with other payloads)."""
    import pytest

    naive = datetime(2026, 5, 3, 12, 0)
    with pytest.raises(ValueError, match="tz-aware"):
        TopicProposedPayload(
            topic_id=uuid4(),
            label="x",
            cluster_signature="x",
            cluster_size=2,
            member_message_ids=["M-1", "M-2"],
            first_seen_at=naive,
            last_seen_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        )


def test_topic_proposed_payload_topic_id_is_uuid() -> None:
    """topic_id must be a UUID — required for projection-row identity."""
    p = TopicProposedPayload(
        topic_id=uuid4(),
        label="x",
        cluster_signature="x",
        cluster_size=2,
        member_message_ids=["M-1", "M-2"],
        first_seen_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
        last_seen_at=datetime(2026, 5, 3, 10, 5, tzinfo=UTC),
    )
    assert isinstance(p.topic_id, UUID)


def test_topic_proposed_payload_cluster_size_min() -> None:
    """cluster_size ≥ 2 — single-message "clusters" never propose a topic."""
    import pytest

    with pytest.raises(ValueError):
        TopicProposedPayload(
            topic_id=uuid4(),
            label="x",
            cluster_signature="x",
            cluster_size=1,
            member_message_ids=["M-1"],
            first_seen_at=datetime(2026, 5, 3, 10, 0, tzinfo=UTC),
            last_seen_at=datetime(2026, 5, 3, 10, 5, tzinfo=UTC),
        )
