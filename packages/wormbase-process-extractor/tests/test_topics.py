"""Tests for ``topics.py`` — text-similarity topic clustering.

Phase 2 Task 2B: ``TopicSynthesisReactivity`` real implementation.
The clustering machinery is parallel to ``recurring.py`` but operates
on any chat text (not just questions) and tracks distinct
``message_id``s per cluster (the topic membership set).

This module is import-cheap: no LLM, no httpx, no ledger. The
Reactivity wires the inference router (and ledger) at fire time.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from wormbase_process_extractor.topics import (
    TopicCluster,
    TopicClusterStore,
    _reset_tenant_topic_store,
    derive_topic_id,
    get_tenant_topic_store,
    update_topic_store_from_chat,
)


def _ts(offset_minutes: int = 0) -> datetime:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC) + timedelta(
        minutes=offset_minutes
    )


def _args(
    *,
    text: str,
    sender: UUID | None = None,
    channel_id: str = "C-finance",
    message_id: str = "M-100",
    ts: datetime | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "sender_person": str(sender or uuid4()),
        "channel_id": channel_id,
        "message_id": message_id,
        "ts": (ts or _ts()).isoformat(),
    }


# ---------------------------------------------------------------------------
# Store basics
# ---------------------------------------------------------------------------


def test_store_starts_empty() -> None:
    store = TopicClusterStore()
    assert store.clusters == []


def test_first_message_creates_single_member_cluster_no_emit() -> None:
    """A novel cluster must not emit until it crosses the threshold (≥2)."""
    store = TopicClusterStore()
    out = update_topic_store_from_chat(
        _args(text="q3 finance reporting cadence weekly"), store=store
    )
    assert out is None
    assert len(store.clusters) == 1
    assert store.clusters[0].cluster_size == 1


def test_empty_text_is_ignored() -> None:
    store = TopicClusterStore()
    out = update_topic_store_from_chat(_args(text=""), store=store)
    assert out is None
    assert store.clusters == []


def test_whitespace_only_text_is_ignored() -> None:
    """Text that normalizes to empty is dropped (no cluster, no emit)."""
    store = TopicClusterStore()
    out = update_topic_store_from_chat(_args(text="the a an"), store=store)
    # The stop-word set strips all tokens; normalized signature is empty.
    assert out is None
    assert store.clusters == []


# ---------------------------------------------------------------------------
# Threshold-cross emission
# ---------------------------------------------------------------------------


def test_two_similar_messages_cross_threshold_and_emit() -> None:
    """Default threshold ≥2 — two messages crossing into the same cluster
    return a payload-shaped dict on the second update."""
    store = TopicClusterStore()
    out1 = update_topic_store_from_chat(
        _args(
            text="q3 finance reporting cadence weekly",
            message_id="M-001",
            ts=_ts(0),
        ),
        store=store,
    )
    assert out1 is None  # below threshold
    out2 = update_topic_store_from_chat(
        _args(
            text="q3 finance reporting cadence",  # similar paraphrase
            message_id="M-002",
            ts=_ts(5),
        ),
        store=store,
    )
    assert out2 is not None
    assert out2["cluster_size"] == 2
    assert out2["member_message_ids"] == ["M-001", "M-002"]
    assert out2["first_seen_at"] == _ts(0)
    assert out2["last_seen_at"] == _ts(5)
    # cluster_signature is the canonical normalized text used for topic_id.
    assert out2["cluster_signature"]


def test_third_message_re_emits_with_growing_cluster_size() -> None:
    """Each subsequent member of an already-emitted cluster re-emits.

    Re-emission is required so the projection table reflects the
    growing cluster_size + last_seen_at without manual reconciliation.
    Idempotency comes from the deterministic topic_id (uuid5 over the
    canonical signature).
    """
    store = TopicClusterStore()
    update_topic_store_from_chat(
        _args(text="q3 finance reporting cadence", message_id="M-001", ts=_ts(0)),
        store=store,
    )
    out2 = update_topic_store_from_chat(
        _args(text="q3 finance reporting cadence", message_id="M-002", ts=_ts(5)),
        store=store,
    )
    assert out2 is not None
    assert out2["cluster_size"] == 2
    out3 = update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-003", ts=_ts(10)),
        store=store,
    )
    assert out3 is not None
    assert out3["cluster_size"] == 3
    assert out3["member_message_ids"] == ["M-001", "M-002", "M-003"]
    assert out3["last_seen_at"] == _ts(10)


def test_dissimilar_messages_form_separate_clusters() -> None:
    """Two unrelated messages each form their own single-member cluster
    and neither crosses the threshold yet."""
    store = TopicClusterStore()
    update_topic_store_from_chat(
        _args(text="q3 net revenue forecast", message_id="M-1"),
        store=store,
    )
    update_topic_store_from_chat(
        _args(text="onboarding pipeline retention metrics", message_id="M-2"),
        store=store,
    )
    assert len(store.clusters) == 2


def test_duplicate_message_id_does_not_inflate_cluster_size() -> None:
    """Replaying the same message into the store must not double-count.

    The Reactivity layer relies on this: if a chat_received entry is
    replayed (deterministic build-from-ledger), the cluster size must
    converge to the same value as a one-shot fold.
    """
    store = TopicClusterStore()
    args = _args(text="q3 finance reporting", message_id="M-001")
    update_topic_store_from_chat(args, store=store)
    out2 = update_topic_store_from_chat(args, store=store)
    # Second observation of the same message_id is a no-op (cluster_size
    # stays at 1 → no emit)
    assert out2 is None
    assert store.clusters[0].cluster_size == 1
    assert store.clusters[0].member_message_ids == ["M-001"]


# ---------------------------------------------------------------------------
# Deterministic topic_id
# ---------------------------------------------------------------------------


def test_derive_topic_id_is_deterministic() -> None:
    """uuid5 over the cluster_signature → same id every replay."""
    sig = "q3 finance reporting cadence"
    a = derive_topic_id(sig)
    b = derive_topic_id(sig)
    assert isinstance(a, UUID)
    assert a == b


def test_derive_topic_id_differs_for_distinct_signatures() -> None:
    a = derive_topic_id("q3 finance reporting")
    b = derive_topic_id("retention metrics")
    assert a != b


def test_emit_payload_carries_deterministic_topic_id() -> None:
    """The topic_id surfaced by the emit dict matches ``derive_topic_id``."""
    store = TopicClusterStore()
    update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-1"), store=store,
    )
    out = update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-2"), store=store,
    )
    assert out is not None
    expected = derive_topic_id(out["cluster_signature"])
    assert out["topic_id"] == expected


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------


def test_per_tenant_stores_are_isolated() -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    _reset_tenant_topic_store(tenant_a)
    _reset_tenant_topic_store(tenant_b)
    store_a = get_tenant_topic_store(tenant_a)
    store_b = get_tenant_topic_store(tenant_b)
    assert store_a is not store_b
    update_topic_store_from_chat(
        _args(text="tenant a topic", message_id="M-A"),
        store=store_a,
    )
    assert len(store_a.clusters) == 1
    assert store_b.clusters == []


def test_get_tenant_topic_store_returns_same_store_on_re_call() -> None:
    """Calling twice for the same tenant returns the same in-memory store
    (the per-tenant accumulator pattern, mirroring system_map.py)."""
    tenant = uuid4()
    _reset_tenant_topic_store(tenant)
    s1 = get_tenant_topic_store(tenant)
    s2 = get_tenant_topic_store(tenant)
    assert s1 is s2


# ---------------------------------------------------------------------------
# Configurable threshold
# ---------------------------------------------------------------------------


def test_higher_threshold_delays_first_emission() -> None:
    """Setting recurring_min=3 means clusters of size 2 do not emit."""
    store = TopicClusterStore(topic_min=3)
    update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-1"), store=store,
    )
    out2 = update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-2"), store=store,
    )
    assert out2 is None  # cluster_size=2 < threshold=3
    out3 = update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-3"), store=store,
    )
    assert out3 is not None
    assert out3["cluster_size"] == 3


# ---------------------------------------------------------------------------
# Cluster dataclass introspection
# ---------------------------------------------------------------------------


def test_topic_cluster_carries_seen_at_metadata() -> None:
    store = TopicClusterStore()
    update_topic_store_from_chat(
        _args(text="q3 finance reporting", message_id="M-1", ts=_ts(0)),
        store=store,
    )
    cluster = store.clusters[0]
    assert isinstance(cluster, TopicCluster)
    assert cluster.first_seen_at == _ts(0)
    assert cluster.last_seen_at == _ts(0)
    assert cluster.member_message_ids == ["M-1"]
    assert cluster.cluster_size == 1
