"""E.1 — recurring-question heuristics lifted from worm-core.

Lifted from ``apps/worm-core/src/wormbase_core/process_extractor.py:780-973``
(the ``_update_recurring_questions`` / ``_find_or_create_cluster`` /
``_emit_recurring_question`` flow plus the ``_Cluster`` dataclass and
the ``_normalize_question`` / ``_levenshtein`` / ``_token_overlap`` /
``_cluster_threshold`` / ``_is_question`` helpers).

**Composition note — do NOT confuse with P10's RecurringQuestionProcessMapperReactivity.**
P10 (``packages/reactivities/src/wormbase_reactivities/process_mapper.py``)
detects recurring (asker, askee, topic) **triplet** patterns from chat
flow and emits ``process_map_proposed`` artifacts. *This* module
clusters by **question-text similarity** (Jaccard token overlap +
Levenshtein) agnostic to asker/askee/topic, and emits
``RecurringQuestionPayload`` artifacts. The two are **complementary
signals** that co-exist via the ledger (spike §8 C6) — both contribute
process-map evidence but from different upstream signals. Future
readers must not conflate them.

The legacy code operated on a *batch* of ``_ChatRow`` and walked all
clusters per batch to decide which to emit; this module reshapes into:

* ``RecurringQuestionStore`` — public per-tenant mutable state holding
  the list of ``Cluster`` rows. Same membership semantics as the legacy
  ``self._clusters`` list, exposed as a public field.
* ``Cluster`` — per-question-text-cluster row with seen-at metadata
  (canonical, occurrences, asked_by, first_seen_at, last_seen_at,
  last_emitted_count). Lifted from ``_Cluster``.
* ``update_from_chat_entry(args, *, store)`` — single-entry reshape.
  Mutates the store with one chat's contribution and returns a
  ``RecurringQuestionPayload`` if (and only if) this entry crossed a
  cluster's recurring threshold (default ≥3) **or** advanced an
  already-emitted cluster's occurrence count further. Returns ``None``
  otherwise.
* ``get_tenant_store(company_id)`` — module-level lazy per-tenant
  registry, mirroring the system-map module's ``_TENANT_ACCUMULATORS``
  pattern.

**Decision-emission boundary:** the legacy ``_emit_recurring_question``
also fired ``data_product_actions.propose_data_product`` at
``occurrences == 3`` (process_extractor.py:850-859). That call is
**not** lifted here. The new shape returns the
``RecurringQuestionPayload`` only; the Reactivity that calls
``update_from_chat_entry`` decides whether to cascade into a
data-product proposal. This keeps the synthesis module deterministic +
import-cheap (no ``data_product_actions`` import, no ledger
dependency, no LLM).

The module is import-cheap: no LLM, no httpx, no Postgres, no ledger
write. The Reactivity wired by Block F.3 obtains the per-tenant store
via ``get_tenant_store`` and calls ``update_from_chat_entry`` per
inbound chat.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from wormbase_ledger.entries import RecurringQuestionPayload

# Stable namespace for question_ids derived from canonical question text.
# Lifted verbatim from process_extractor.py:67.
_QUESTION_NAMESPACE = UUID("8a3f9e2d-7b4c-4d1a-9e8f-1a2b3c4d5e6f")

# Default minimum occurrences before a cluster emits as recurring.
# Lifted from process_extractor.py:370 (``self._recurring_min``).
_DEFAULT_RECURRING_MIN = 3


# ---------------------------------------------------------------------------
# Heuristics — lifted verbatim from process_extractor.py:114-177
# ---------------------------------------------------------------------------


def _is_question(text: str) -> bool:
    """Lifted verbatim from process_extractor.py:114-122."""
    if not text:
        return False
    if "?" in text:
        return True
    return bool(
        re.match(
            r"^\s*(what|why|how|when|who|where|did|do|does|is|are|was|were|can|could|should)\b",
            text,
            re.IGNORECASE,
        )
    )


# Stop-word set used by ``_normalize_question`` to strip pronouns / fillers
# before clustering. Lifted verbatim from process_extractor.py:125-133.
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did",
    "i", "you", "we", "they", "he", "she", "it", "this", "that",
    "to", "of", "in", "on", "at", "for", "by", "with", "and", "or",
    "from", "but", "as", "if", "be", "been", "being", "am", "my",
    "our", "your", "their", "his", "her", "its", "me", "us",
    "what's", "whats", "what", "why", "how", "when", "who", "where",
    "can", "could", "should", "would", "have", "has", "had",
}


def _normalize_question(text: str) -> str:
    """Lowercase, strip punctuation/pronouns, keep nouns/verbs (heuristic).

    Lifted verbatim from process_extractor.py:136-141.
    """
    lo = text.lower()
    lo = re.sub(r"[^\w\s]", " ", lo)
    tokens = [t for t in lo.split() if t and t not in _STOP and len(t) > 1]
    return " ".join(tokens)


def _levenshtein(a: str, b: str) -> int:
    """Lifted verbatim from process_extractor.py:144-160."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            ins = curr[j - 1] + 1
            dele = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]


def _cluster_threshold(s: str) -> int:
    """Lifted verbatim from process_extractor.py:163-168.

    Allow generous character drift for clustering — paraphrases routinely
    add or drop a qualifier ("this quarter", "do we have", "right now").
    Tuned to keep "q3 net revenue" and "q3 net revenue quarter" in the
    same cluster but to keep "deploy plan" out of "q3 net revenue".
    """
    return max(4, len(s) // 2)


def _token_overlap(a: str, b: str) -> float:
    """Jaccard token overlap, used as a lightweight cluster pre-check.

    Lifted verbatim from process_extractor.py:171-177.
    """
    sa = set(a.split())
    sb = set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# Cluster + Store
# ---------------------------------------------------------------------------


@dataclass
class Cluster:
    """A cluster of normalized-question variants with seen-at metadata.

    Lifted from ``_Cluster`` (process_extractor.py:185-194). Renamed from
    the underscore-prefixed legacy name because this module exposes the
    type as part of its public contract (tests + Reactivity inspect
    cluster fields directly).
    """

    canonical: str
    occurrences: int = 0
    asked_by: set[UUID] = field(default_factory=set)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_emitted_count: int = 0  # how many occurrences when we last emitted


@dataclass
class RecurringQuestionStore:
    """Per-tenant mutable cluster registry.

    Holds the equivalent of the legacy ``self._clusters: list[_Cluster]``
    plus the configurable threshold. The store is the single source of
    truth for one tenant's recurring-question state across many
    ``update_from_chat_entry`` calls.
    """

    clusters: list[Cluster] = field(default_factory=list)
    recurring_min: int = _DEFAULT_RECURRING_MIN

    def find_or_create_cluster(self, normalized: str) -> Cluster:
        """Find a cluster matching ``normalized`` or create a new one.

        Lifted from ``_find_or_create_cluster``
        (process_extractor.py:802-817). Two paths into the same cluster:
        high token overlap **OR** small Levenshtein distance. Token
        overlap catches "q3 net revenue" vs "q3 net revenue this quarter"
        (extra qualifier) cleanly; Levenshtein catches typos / inflection
        drift.
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
        c = Cluster(canonical=normalized)
        self.clusters.append(c)
        return c


# ---------------------------------------------------------------------------
# Per-tenant module-level registry
# ---------------------------------------------------------------------------


# Mirrors ``_TENANT_ACCUMULATORS`` in
# ``packages/wormbase-process-extractor/src/wormbase_process_extractor/system_map.py:180``.
# Same caveat: the dict is per-process; cross-process Reactivity dispatch
# would need a projection-backed store. Out of scope for v1.
_TENANT_QUESTION_STORES: dict[UUID, RecurringQuestionStore] = {}


def get_tenant_store(company_id: UUID) -> RecurringQuestionStore:
    """Lazily construct and return the per-tenant ``RecurringQuestionStore``.

    Reactivity wiring (Block F.3) calls this once per fire to obtain the
    living store before invoking :func:`update_from_chat_entry`.
    """
    store = _TENANT_QUESTION_STORES.get(company_id)
    if store is None:
        store = RecurringQuestionStore()
        _TENANT_QUESTION_STORES[company_id] = store
    return store


def _reset_tenant_store(company_id: UUID) -> None:
    """Test hook — drop one tenant's store state."""
    _TENANT_QUESTION_STORES.pop(company_id, None)


# ---------------------------------------------------------------------------
# Single-entry update + payload synthesis
# ---------------------------------------------------------------------------


def _build_payload(cluster: Cluster) -> RecurringQuestionPayload:
    """Build a ``RecurringQuestionPayload`` from a cluster's current state.

    Lifted from ``_emit_recurring_question`` (process_extractor.py:819-842),
    minus the ledger-write side effect. ``question_id`` is deterministic
    (uuid5 over the canonical question text), so re-emitting a cluster
    produces a stable id — the projection layer dedupes naturally.
    """
    question_id = uuid5(_QUESTION_NAMESPACE, cluster.canonical)
    first_seen = cluster.first_seen_at
    last_seen = cluster.last_seen_at or first_seen
    assert first_seen is not None  # update_from_chat_entry sets this first
    suggested = (
        f"daily digest: {cluster.canonical}"
        if cluster.occurrences >= 4
        else None
    )
    return RecurringQuestionPayload(
        question_id=question_id,
        normalized_question=cluster.canonical[:256],
        asked_by_persons=sorted(cluster.asked_by, key=str),
        occurrences=cluster.occurrences,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        suggested_automation=suggested,
    )


def _parse_ts(raw: Any) -> datetime | None:
    """Parse the entry's ``ts`` field. Returns ``None`` on bad input.

    Accepts a ``datetime`` directly or an ISO-8601 string. Mirrors the
    legacy ``_ChatRow.ts`` shape (always a tz-aware ``datetime`` after
    ingest); here we accept both because the args dict carries
    JSON-serializable values.
    """
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def update_from_chat_entry(
    args: dict[str, Any],
    *,
    store: RecurringQuestionStore,
) -> RecurringQuestionPayload | None:
    """Mutate ``store`` with one ``chat_received`` entry's contribution.

    Reads ``args["text"]``, ``args["sender_person"]``, ``args["ts"]`` and
    folds them into a similarity cluster. Returns a
    ``RecurringQuestionPayload`` iff this entry advances a cluster past
    its recurring threshold (or further, on subsequent occurrences).
    Returns ``None`` for non-questions, empty-token-set normalizations,
    and clusters still below threshold.

    Mirrors the legacy ``_update_recurring_questions``
    (process_extractor.py:780-800), reshaped from batch-walk to
    single-entry. The ``last_emitted_count`` guard is preserved so a
    stable replay of the same chat sequence emits the same number of
    payloads in the same order.
    """
    text = args.get("text")
    if not isinstance(text, str) or not _is_question(text):
        return None
    norm = _normalize_question(text)
    if not norm:
        return None

    sender_raw = args.get("sender_person")
    sender_id: UUID | None = None
    if sender_raw is not None:
        try:
            sender_id = (
                sender_raw if isinstance(sender_raw, UUID) else UUID(str(sender_raw))
            )
        except (ValueError, AttributeError):
            sender_id = None

    ts = _parse_ts(args.get("ts"))

    cluster = store.find_or_create_cluster(norm)
    cluster.occurrences += 1
    if sender_id is not None:
        cluster.asked_by.add(sender_id)
    if cluster.first_seen_at is None and ts is not None:
        cluster.first_seen_at = ts
    if ts is not None:
        cluster.last_seen_at = ts

    if cluster.occurrences < store.recurring_min:
        return None
    if cluster.occurrences == cluster.last_emitted_count:
        return None

    payload = _build_payload(cluster)
    cluster.last_emitted_count = cluster.occurrences
    return payload


__all__ = [
    "Cluster",
    "RecurringQuestionStore",
    "_reset_tenant_store",
    "get_tenant_store",
    "update_from_chat_entry",
]
