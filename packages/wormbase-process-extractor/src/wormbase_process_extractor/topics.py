"""Phase 2 Task 2B — text-similarity topic clustering for chat traffic.

Parallel to ``recurring.py`` but operates on **any chat text** (not
just questions) and tracks distinct ``message_id``s per cluster.

The clustering primitives (``_normalize_question`` →
``_normalize_text``, ``_levenshtein``, ``_token_overlap``,
``_cluster_threshold``) are imported from ``recurring`` so the two
similarity surfaces stay byte-equivalent on shared inputs. Differences
from ``recurring.py``:

* No question filter — every non-empty normalized text contributes.
* Per-cluster member set is the list of distinct ``message_id``s that
  fell into the cluster (in insertion order). Re-ingesting the same
  ``message_id`` is idempotent — required for deterministic ledger
  replay (the Reactivity layer relies on this so build-from-ledger
  converges to the same projection state as the live fold).
* Each post-threshold update returns a ready-to-emit dict (not a
  Pydantic payload) so the Reactivity can mix in
  ``label`` / ``confidence`` / ``served_by`` from the inference router
  before it builds a ``TopicProposedPayload``.

The module is import-cheap: no LLM, no httpx, no ledger. The
``TopicSynthesisReactivity`` injects the inference router at fire
time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

# Import the in-package primitives — these are private to the package
# but documented as the canonical text-similarity surface (recurring.py
# docstring explicitly notes the symbols are "the public contract"
# within this package's clustering modules).
from wormbase_process_extractor.recurring import (
    _cluster_threshold,
    _levenshtein,
    _normalize_question as _normalize_text,
    _parse_ts,
    _token_overlap,
)

# Stable namespace for topic_ids derived from cluster signatures.
# Distinct from the ``_QUESTION_NAMESPACE`` in recurring.py so the
# topic surface and the recurring-question surface never collide on
# the same canonical text.
_TOPIC_NAMESPACE = UUID("3c5e8d2f-9b1a-4f7c-bd2e-5a8f6c7d4e9b")

# Default minimum cluster size before a cluster emits. Two crossings
# is the lowest defensible threshold — a single repeated reference is
# the smallest signal that a cluster represents a recurring topic
# rather than a one-off mention. Tunable via the Reactivity factory.
_DEFAULT_TOPIC_MIN = 2


def derive_topic_id(cluster_signature: str) -> UUID:
    """Deterministic topic id for a normalized cluster signature.

    Same shape as ``RecurringQuestionPayload.question_id`` derivation
    in ``recurring.py`` — uuid5 over the canonical text — so a replay
    of the same ledger lands the same topic_id and the projection
    fold is byte-stable.
    """
    return uuid5(_TOPIC_NAMESPACE, cluster_signature)


@dataclass
class TopicCluster:
    """A cluster of normalized-text variants with seen-at metadata.

    Mirrors ``recurring.Cluster`` shape, with a couple of differences:

    * ``cluster_size`` is the count of **distinct message_ids**, not
      raw call count — re-ingesting the same message_id (deterministic
      replay) is idempotent.
    * ``member_message_ids`` preserves insertion order; ``last_emit_size``
      gates re-emit so growth-only updates re-emit (mirroring
      ``Cluster.last_emitted_count``).
    """

    canonical: str
    cluster_size: int = 0
    member_message_ids: list[str] = field(default_factory=list)
    member_message_id_set: set[str] = field(default_factory=set)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_emit_size: int = 0  # cluster_size at last emit; gates re-emit


@dataclass
class TopicClusterStore:
    """Per-tenant mutable cluster registry for topics.

    Mirrors ``recurring.RecurringQuestionStore`` so the wire-up patterns
    are consistent across the two synthesis modules. ``topic_min`` is
    the minimum cluster_size before a cluster's first emit (default 2);
    subsequent emits re-fire on every distinct-message_id growth.
    """

    clusters: list[TopicCluster] = field(default_factory=list)
    topic_min: int = _DEFAULT_TOPIC_MIN

    def find_or_create_cluster(self, normalized: str) -> TopicCluster:
        """Find a cluster matching ``normalized`` or create a new one.

        Two paths into the same cluster: high token overlap **OR** small
        Levenshtein distance — same composition as
        ``recurring.RecurringQuestionStore.find_or_create_cluster`` so
        a paraphrase clusters consistently across both surfaces.
        """
        for c in self.clusters:
            if _token_overlap(c.canonical, normalized) >= 0.5:
                return c
            threshold = _cluster_threshold(
                c.canonical
                if len(c.canonical) >= len(normalized)
                else normalized
            )
            if _levenshtein(c.canonical, normalized) <= threshold:
                return c
        c = TopicCluster(canonical=normalized)
        self.clusters.append(c)
        return c


# ---------------------------------------------------------------------------
# Per-tenant module-level registry
# ---------------------------------------------------------------------------


# Mirrors ``_TENANT_QUESTION_STORES`` in ``recurring.py`` and
# ``_TENANT_ACCUMULATORS`` in ``system_map.py``. Same caveat: the dict
# is per-process. Cross-process Reactivity dispatch would need a
# projection-backed store; v1 of TopicSynthesisReactivity runs in the
# single-process Reactivity dispatcher.
_TENANT_TOPIC_STORES: dict[UUID, TopicClusterStore] = {}


def get_tenant_topic_store(company_id: UUID) -> TopicClusterStore:
    """Lazily construct and return the per-tenant ``TopicClusterStore``.

    Reactivity wiring calls this once per fire to obtain the living
    store before invoking :func:`update_topic_store_from_chat`.
    """
    store = _TENANT_TOPIC_STORES.get(company_id)
    if store is None:
        store = TopicClusterStore()
        _TENANT_TOPIC_STORES[company_id] = store
    return store


def _reset_tenant_topic_store(company_id: UUID) -> None:
    """Test hook — drop one tenant's topic-store state."""
    _TENANT_TOPIC_STORES.pop(company_id, None)


# ---------------------------------------------------------------------------
# Single-entry update + emit-dict synthesis
# ---------------------------------------------------------------------------


def _build_emit_dict(cluster: TopicCluster) -> dict[str, Any]:
    """Build a ready-to-emit dict from a cluster's current state.

    Mirrors ``recurring._build_payload`` shape, but returns a plain
    dict because the Reactivity layer mixes in
    ``label`` / ``confidence`` / ``served_by`` from the inference
    router before constructing ``TopicProposedPayload``. Doing the
    inference call in the Reactivity (not here) keeps this module
    import-cheap.

    ``topic_id`` is deterministic (uuid5 over the canonical signature)
    so re-emit on a growing cluster lands the same id and the
    projection layer dedupes naturally.
    """
    assert cluster.first_seen_at is not None
    assert cluster.last_seen_at is not None
    return {
        "topic_id": derive_topic_id(cluster.canonical),
        "cluster_signature": cluster.canonical[:512],
        "cluster_size": cluster.cluster_size,
        "member_message_ids": list(cluster.member_message_ids),
        "first_seen_at": cluster.first_seen_at,
        "last_seen_at": cluster.last_seen_at,
    }


def update_topic_store_from_chat(
    args: dict[str, Any],
    *,
    store: TopicClusterStore,
) -> dict[str, Any] | None:
    """Mutate ``store`` with one ``chat_received`` entry's contribution.

    Reads ``args["text"]``, ``args["message_id"]``, ``args["ts"]`` and
    folds them into a topic cluster. Returns an emit-dict iff this
    entry advances a cluster past its threshold (or further, on
    subsequent distinct-message_id observations). Returns ``None`` for
    empty / stop-word-only text and for clusters still below threshold.

    Idempotency: re-ingesting the same ``message_id`` is a no-op (the
    cluster's distinct-id set guards against double-counting). This
    is required for deterministic ledger replay.
    """
    text = args.get("text")
    if not isinstance(text, str) or not text:
        return None
    norm = _normalize_text(text)
    if not norm:
        return None

    message_id_raw = args.get("message_id")
    message_id = str(message_id_raw) if message_id_raw is not None else ""

    ts = _parse_ts(args.get("ts"))

    cluster = store.find_or_create_cluster(norm)

    if message_id and message_id not in cluster.member_message_id_set:
        cluster.member_message_id_set.add(message_id)
        cluster.member_message_ids.append(message_id)
        cluster.cluster_size += 1
    elif not message_id:
        # Defensive: an entry without a message_id still bumps the
        # count once, but only the first such occurrence (subsequent
        # missing-id entries collapse onto the same sentinel slot).
        sentinel = "__no_message_id__"
        if sentinel not in cluster.member_message_id_set:
            cluster.member_message_id_set.add(sentinel)
            cluster.member_message_ids.append(sentinel)
            cluster.cluster_size += 1
    # else: known message_id — no-op (idempotent replay).

    if cluster.first_seen_at is None and ts is not None:
        cluster.first_seen_at = ts
    if ts is not None:
        cluster.last_seen_at = ts

    if cluster.cluster_size < store.topic_min:
        return None
    if cluster.cluster_size == cluster.last_emit_size:
        return None

    emit_dict = _build_emit_dict(cluster)
    cluster.last_emit_size = cluster.cluster_size
    return emit_dict


__all__ = [
    "TopicCluster",
    "TopicClusterStore",
    "_reset_tenant_topic_store",
    "derive_topic_id",
    "get_tenant_topic_store",
    "update_topic_store_from_chat",
]
