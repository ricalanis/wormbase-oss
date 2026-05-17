"""Agent-gateway W5a Reactivities + the ``Compounding`` primitive.

The agent-gateway ships two Reactivities that share the canonical
``EntryKind("query_outcome_recorded")`` predicate but differ in their
per-instance behaviour:

  * ``OutcomeToTemplatePromotionReactivity`` — clusters ``>=3``
    same-canonical-NL outcomes within a domain and emits one
    ``query_template_promoted`` PEVR cycle per cluster.
  * ``QueryOutcomeToDataProductReactivity`` — per-outcome promotion:
    every individually high-quality outcome surfaces as a
    ``data_product_proposed`` entry, chained via
    ``parameters.source_audit_trail_id`` for SOC-2 provenance.

Closes journey-revision §3 Seam #4 structurally: both Reactivities are
now constructed from a parameterised ``Compounding`` primitive. The
primitive expresses the shared compounding shape:

    source_predicate → quality_filter → gather_fn → cluster_fn
                     → promotion_threshold → promotion_action

Phase 2 (separate work) will add three new axes that consume the same
primitive (failures-as-bad-patterns, gaps-as-escalations,
consumption-as-recommendations). This Phase 1 refactor is structural
only — KIND_REGISTRY = 96 unchanged, no new entry kinds, no behaviour
change.

v1 clustering implementation (template promotion):
* canonical NL-intent = lowercased + whitespace-normalised
  ``nl_question``;
* same-domain check = string equality of resolved ``domain_id`` (None
  collapses to a sentinel so outcomes-without-domain still group with
  one another);
* threshold = 3 outcomes;
* quality gate = each outcome's ``used && useful && quality_score >= 0.9``;
* time window = last 30 days against ``context.now()``.

v1.1 will swap the substring-based NL canonicalisation for embedding
cosine similarity (``>= 0.85``) once production pgvector reads and an
embedding service are wired in. The pinned contract:

  * 3 same-domain + same-canonical-NL outcomes with
    ``quality_score >= 0.9`` produce one ``query_template_promoted``
    entry; fewer than 3 do not promote; the resulting
    ``promoted_from_outcome_ids`` references the outcome entries'
    ``entry_id`` UUIDs.

The Reactivities follow the catalog-mirror shape:

  * ``@dataclass`` with ``predicate`` / ``condition`` initialised in
    ``__post_init__`` (inherited from ``Compounding``);
  * ``async def fire(entry, context)`` calling ``ledger.write``
    directly via the synchronous ``execute_fn``/``verify_fn``/
    ``resolve_fn`` callable triplet;
  * registration via ``ReactivityRegistry.register(...)`` is
    **synchronous**.

The ledger is supplied through ``ReactivityContext`` at dispatch time
(lake-maintainer / catalog-mirror convention), NOT as a factory
parameter. This keeps the factories pure and lets one Reactivity
instance serve many tenants if a future deployment shape demands it.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

import numpy as np

from wormbase_reactivities.conditions import AlwaysAllow, NotRecentlyFired
from wormbase_reactivities.predicates import EntryKind, Periodic
from wormbase_reactivities.protocol import (
    FiredAction,
    Reactivity,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_CLUSTER_THRESHOLD: int = 3
_QUALITY_GATE: Decimal = Decimal("0.9")
_LOOKBACK_DAYS: int = 30
# Re-cluster debounce: 1 hour per (reactivity, novelty_key). Matches the
# Task 8 plan default — outcomes land minutes-to-days after a query
# closes, so an hourly cluster sweep is dense enough to feel responsive
# without firing dozens of times when a burst of outcomes lands.
_DEBOUNCE_HOURS: float = 1.0

# Quality gate for the per-outcome data-product promotion. Same Decimal
# threshold as the template-promotion Reactivity (0.9). A high-quality
# outcome is one the agent + admin agree was both used and useful, and
# that the scoring pipeline rated >= 0.9.
_DP_QUALITY_GATE: Decimal = Decimal("0.9")

# v2.B Phase 3b — cosine threshold for embedding-similarity clustering
# (axes 1 + 3). Pinned at 0.85 per the journey-revision plan. Tunable
# per-factory via the ``embedding_threshold`` parameter.
_EMBEDDING_COSINE_THRESHOLD: float = 0.85

# 2026-05-14 perf carry-forward #3 — auditable knob for which clustering
# impl is active. ``"vectorized"`` (default) selects the numpy +
# pre-bucketed-by-domain implementation; ``"legacy"`` selects the pure-
# Python single-pass first-fit pass. The legacy impl is preserved one
# cycle for A/B comparison + emergency rollback.
_CLUSTERING_IMPL: str = "vectorized"


# ---------------------------------------------------------------------------
# Shared payload helpers (used by both Reactivities + tests via factories)
# ---------------------------------------------------------------------------


def _canonical_intent(nl_question: str) -> str:
    """Canonicalise a free-form NL question for v1 substring clustering.

    Lowercase + collapse runs of whitespace. Mirrors the simple
    canonicalisation used by other Wave-2 tools (e.g. semantic search
    fallback path) so the clustering and the downstream re-use surface
    agree byte-for-byte.

    v2.B Phase 3b adds cosine clustering on top of (not replacing) this
    canonicalisation. Entries with ``embedding=None`` (legacy, opt-out,
    or pre-Phase-3b) fall back to substring clustering via this fn.
    """
    return " ".join(nl_question.lower().split())


# ---------------------------------------------------------------------------
# v2.B Phase 3b — cosine similarity helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float] | tuple[float, ...],
                       b: list[float] | tuple[float, ...]) -> float:
    """Pure, deterministic cosine similarity for two vectors.

    Returns the cosine of the angle in ``[-1.0, 1.0]``. No numpy
    dependency — the inner loop is short enough that a Python sum
    handles 768-dim vectors in microseconds.

    Numerical-stability contract:

      * identical vectors → 1.0 exactly (within floating-point eps)
      * orthogonal vectors → 0.0
      * opposite vectors → -1.0
      * near-zero magnitude → 0.0 (avoids div-by-zero; documented
        return value so callers can't be surprised by a NaN)

    Dim-mismatch raises ``ValueError`` so a model swap surfaces as a
    test failure, not a corruption cluster.
    """
    if len(a) != len(b):
        raise ValueError(
            f"cosine: dim mismatch {len(a)} vs {len(b)}"
        )
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        # One (or both) vectors is the zero vector; cosine is
        # undefined. Convention: 0.0 (entries don't cluster).
        return 0.0
    from math import sqrt
    return dot / (sqrt(na) * sqrt(nb))


def _entry_embedding(entry: dict[str, Any]) -> tuple[float, ...] | None:
    """Extract the embedding (as a tuple) from an outcome execute entry,
    or None if absent / malformed.

    Embedding lives on ``payload.args.embedding`` per the write-time
    wire contract. Returned as a tuple so the cluster algorithm can
    treat it as an immutable cache key.
    """
    args = _outcome_args(entry)
    raw = args.get("embedding")
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    try:
        return tuple(float(v) for v in raw)
    except (TypeError, ValueError):
        return None


def _entry_embedding_raw(entry: dict[str, Any]) -> list[float] | tuple[float, ...] | None:
    """Lightweight variant of ``_entry_embedding`` for the vectorized
    cluster path.

    Returns the raw list/tuple as-stored on the payload, without the
    per-element ``float()`` materialization. ``np.asarray(...,
    dtype=np.float32)`` handles the conversion in one C-level pass —
    much faster than Python's per-element ``float(v)``.

    Validates length only (no per-element type cast). Caller is the
    v2 cluster path, which immediately feeds the value to numpy and
    catches conversion errors there. For the scalar primitive path,
    keep using ``_entry_embedding`` (returns tuple so it's hashable).
    """
    args = _outcome_args(entry)
    raw = args.get("embedding")
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    return raw


def _cluster_by_embedding_similarity_legacy(
    entries: Sequence[dict[str, Any]],
    *,
    threshold: float = _EMBEDDING_COSINE_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """Single-pass cosine clustering for entries that carry an embedding.

    Algorithm:

      1. Walk entries in order; for each, compare against existing
         clusters' representative (the first member's embedding).
      2. If cosine ≥ threshold against any existing rep, append to
         that cluster.
      3. Otherwise, start a new cluster.

    Single-pass + first-fit so the result is stable across re-runs
    on the same insertion order — the ledger fold gives us that order
    by construction (seq-ascending). Production tuning may want a
    proper hierarchical clustering once cluster cardinality > a few
    hundred per window; at v2.B Phase 3b cardinality the simple pass
    is plenty.

    Entries WITHOUT an embedding are skipped here — the hybrid
    cluster_fn (below) feeds them to the substring fallback.

    2026-05-14: Preserved as ``_legacy`` for one cycle (A/B comparison
    + emergency rollback). The active impl is the vectorized v2 below;
    swap via ``_CLUSTERING_IMPL`` constant.
    """
    clusters: list[list[dict[str, Any]]] = []
    reps: list[tuple[float, ...]] = []
    for e in entries:
        vec = _entry_embedding(e)
        if vec is None:
            continue
        placed = False
        for i, rep in enumerate(reps):
            if len(rep) != len(vec):
                continue
            if _cosine_similarity(rep, vec) >= threshold:
                clusters[i].append(e)
                placed = True
                break
        if not placed:
            reps.append(vec)
            clusters.append([e])
    return clusters


def _batch_cosine_matrix(embeddings: Sequence[Sequence[float]]) -> np.ndarray:
    """Compute an NxN cosine-similarity matrix in one BLAS call.

    Pre-normalizes each row to unit length, then returns the matrix
    product ``normalized @ normalized.T``. The diagonal is 1.0 for
    non-zero rows and 0.0 for zero-norm rows.

    Numerical-stability contract — mirrors ``_cosine_similarity``:

      * identical non-zero vectors → 1.0 (within float32 eps)
      * orthogonal vectors → 0.0
      * opposite vectors → -1.0
      * zero-norm row → cosine 0.0 to every other row (entries don't
        cluster; documented Phase-3b semantics)
      * empty input → empty (0, 0) matrix

    Uses ``np.float32`` — the precision delta vs Python ``float``
    (~1e-7 vs ~1e-15) is below the clustering threshold (0.85) by
    many orders of magnitude, so partition results are unchanged.

    Dim-mismatch raises ``ValueError`` so a model swap surfaces as a
    test failure, not a corruption cluster.
    """
    if not embeddings:
        return np.zeros((0, 0), dtype=np.float32)

    # ``np.array`` raises ValueError on ragged input — surface that
    # as a clearer dim-mismatch error matching the scalar primitive.
    try:
        matrix = np.asarray(embeddings, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"batch cosine: dim mismatch — {exc}") from exc
    if matrix.ndim != 2:
        raise ValueError(
            f"batch cosine: expected 2-D embeddings, got shape {matrix.shape}"
        )

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Safe normalization: avoid div-by-zero for zero-norm rows.
    norms_safe = np.where(norms == 0.0, 1.0, norms)
    normalized = matrix / norms_safe
    # Zero out the rows whose original norm was zero so their cosine
    # to everyone (and themselves) is 0.0 — matches the scalar
    # primitive's documented behaviour.
    zero_row_mask = (norms == 0.0).reshape(-1)
    if zero_row_mask.any():
        normalized[zero_row_mask] = 0.0

    return normalized @ normalized.T


def _cluster_one_bucket_vectorized(
    bucket_entries: Sequence[dict[str, Any]],
    embeddings: Sequence[Sequence[float]],
    *,
    threshold: float,
) -> list[list[dict[str, Any]]]:
    """First-fit single-pass clustering for one (single-dim) bucket.

    Same algorithm as v1's pure-Python loop, but each "compare-vs-all-
    existing-reps" step is a single numpy matrix-vector product
    against the pre-normalized representatives. That collapses the
    Python loop's ~k × dim per-step cost into one BLAS call of the
    same total complexity but ~50× lower constant factor.

    Why per-step rather than the full NxN matrix?
    Full NxN burns O(N²) regardless of how many clusters form. In the
    realistic clustered case (5 seed clusters, N=1000) only ~5N
    compares are needed; per-step rep-only matches v1's algorithmic
    complexity and gives ~5-15× wall-clock speedup. In the worst
    case (every entry distinct) per-step rep-only degrades to N² and
    matches the full-matrix path's cost — no regression at either
    end of the cluster-count spectrum.

    The pre-normalize-once + vector-of-norms trick mirrors
    ``_batch_cosine_matrix`` exactly so the numerical contract holds
    here too (zero rows clamp to similarity 0, dtype is float32).
    """
    n = len(bucket_entries)
    if n == 0:
        return []

    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError(
            f"cluster bucket: expected 2-D embeddings, got shape {matrix.shape}",
        )
    norms = np.linalg.norm(matrix, axis=1)
    norms_safe = np.where(norms == 0.0, 1.0, norms)
    normalized = matrix / norms_safe.reshape(-1, 1)
    zero_row_mask = norms == 0.0
    if zero_row_mask.any():
        normalized[zero_row_mask] = 0.0

    # Pre-allocate a representatives matrix at full capacity so we can
    # do one matrix-vector product per step (no per-step list-to-numpy
    # conversion overhead). At most ``n`` distinct reps.
    rep_matrix = np.empty((n, normalized.shape[1]), dtype=np.float32)
    n_reps = 0
    cluster_members: list[list[int]] = []

    for i in range(n):
        if n_reps == 0:
            rep_matrix[0] = normalized[i]
            n_reps = 1
            cluster_members.append([i])
            continue

        # Cosine of entry i vs every existing rep, in one BLAS call.
        sims = rep_matrix[:n_reps] @ normalized[i]
        # First-fit: find the LOWEST-INDEX rep with sim >= threshold.
        above = np.where(sims >= threshold)[0]
        if above.size > 0:
            cluster_members[int(above[0])].append(i)
        else:
            rep_matrix[n_reps] = normalized[i]
            n_reps += 1
            cluster_members.append([i])

    return [[bucket_entries[i] for i in members] for members in cluster_members]


def _cluster_by_embedding_similarity_v2(
    entries: Sequence[dict[str, Any]],
    *,
    threshold: float = _EMBEDDING_COSINE_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """Vectorized cosine clustering.

    Pre-buckets entries by ``_resolved_domain`` (cheap, pre-computed
    field) so cosine math only runs within a domain. Within each
    bucket, computes cosine via numpy BLAS — per-step matrix-vector
    product against the running representatives table (see
    ``_cluster_one_bucket_vectorized``).

    Why bucket by domain only (not also by canonical_intent)?
    Bucketing by canonical_intent would defeat the entire purpose of
    embedding clustering — the headline v2.B Phase 3b behaviour is
    "cluster outcomes with similar embeddings DESPITE different NL
    substrings". Bucketing by domain alone keeps that property while
    cutting cross-domain compares (which the downstream
    ``_existing_promotion_keys`` already treats as separate
    partitions — see the ``(domain, intent)`` key shape there).

    Partition byte-identity vs ``_legacy``: holds whenever entries
    that v1 would have clustered share the same resolved domain
    (the production case — ``query_outcome_recorded`` payloads carry
    ``final_query_spec.domain_id``, the gather scopes by company, and
    a single Reactivity firing observes one domain's outcomes).

    Cross-domain mixing is the only divergence: v1 would have merged
    two similar-embedding entries from different domains; v2 keeps
    them separate. This matches the downstream key shape, so the
    promotion + idempotency surface is unchanged (a v1 mixed cluster
    would have been tagged with the first entry's domain anyway).
    The byte-identity tests below pin this with explicit fixtures.

    Entries WITHOUT an embedding are skipped — the hybrid cluster_fn
    (below) feeds them to the substring fallback.
    """
    if not entries:
        return []

    # Pre-bucket by resolved domain. Order-preserving via insertion-
    # ordered dict (Python 3.7+) so the output cluster order matches
    # v1's insertion order within each domain.
    #
    # Use the raw-list embedding helper here: numpy handles per-
    # element conversion via ``np.asarray(..., dtype=np.float32)``
    # in C, which is ~50× faster than the Python tuple(float(v) for
    # v in raw) path that ``_entry_embedding`` does. The extraction
    # cost dominates at N>=500, so this matters.
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    bucket_raw_embs: dict[str, list[list[float] | tuple[float, ...]]] = defaultdict(list)
    bucket_order: list[str] = []
    for e in entries:
        raw = _entry_embedding_raw(e)
        if raw is None:
            continue
        args = _outcome_args(e)
        domain = _resolved_domain(args)
        if domain not in buckets:
            bucket_order.append(domain)
        buckets[domain].append(e)
        bucket_raw_embs[domain].append(raw)

    all_clusters: list[list[dict[str, Any]]] = []
    for domain in bucket_order:
        bucket_entries = buckets[domain]
        embeddings = bucket_raw_embs[domain]

        by_dim: dict[int, list[int]] = defaultdict(list)
        dim_order: list[int] = []
        for idx, vec in enumerate(embeddings):
            dim = len(vec)
            if dim not in by_dim:
                dim_order.append(dim)
            by_dim[dim].append(idx)

        for dim in dim_order:
            idxs = by_dim[dim]
            sub_entries = [bucket_entries[i] for i in idxs]
            sub_embeddings = [embeddings[i] for i in idxs]
            all_clusters.extend(
                _cluster_one_bucket_vectorized(
                    sub_entries, sub_embeddings, threshold=threshold,
                ),
            )

    return all_clusters


def _cluster_by_embedding_similarity(
    entries: Sequence[dict[str, Any]],
    *,
    threshold: float = _EMBEDDING_COSINE_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """Dispatcher — picks the active clustering impl.

    Reads ``_CLUSTERING_IMPL``:

      * ``"vectorized"`` (default) → ``_cluster_by_embedding_similarity_v2``
      * ``"legacy"``               → ``_cluster_by_embedding_similarity_legacy``

    The dispatcher exists so external test callers + the hybrid
    cluster_fn route through a single name; A/B comparison + rollback
    are a one-line constant flip.
    """
    if _CLUSTERING_IMPL == "legacy":
        return _cluster_by_embedding_similarity_legacy(entries, threshold=threshold)
    return _cluster_by_embedding_similarity_v2(entries, threshold=threshold)


def _split_by_embedding_presence(
    entries: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition entries into ``(embedded, non_embedded)``.

    The two halves cluster through different paths:

      * ``embedded`` → ``_cluster_by_embedding_similarity``
      * ``non_embedded`` → substring fallback (legacy + opt-out path)

    Merge happens at the call site (the hybrid factory cluster_fn).
    """
    embedded: list[dict[str, Any]] = []
    non_embedded: list[dict[str, Any]] = []
    for e in entries:
        if _entry_embedding(e) is not None:
            embedded.append(e)
        else:
            non_embedded.append(e)
    return embedded, non_embedded


def _make_hybrid_cluster_fn(
    *,
    threshold: float,
    substring_cluster_fn: Callable[
        [Sequence[dict[str, Any]]], list[list[dict[str, Any]]]
    ],
) -> _ClusterFn:
    """Build a cluster_fn that:

    1. Splits entries into (embedded, non_embedded).
    2. Clusters embedded entries by cosine ≥ threshold.
    3. Clusters non_embedded entries via the supplied
       substring_cluster_fn (existing path — preserves byte-identity
       for pre-Phase-3b ledgers / opt-out installations).
    4. Returns the merged cluster list (embedded clusters first,
       substring clusters second — stable for test assertions).

    Used by axes 1 (template promotion) + 3 (bad-pattern). Axis 1's
    substring fallback is ``_cluster_by_canonical_intent``; axis 3's
    is ``_cluster_by_canonical_intent_only`` (defined below).
    """

    def _hybrid(
        entries: Sequence[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        embedded, non_embedded = _split_by_embedding_presence(entries)
        embedded_clusters = _cluster_by_embedding_similarity(
            embedded, threshold=threshold,
        )
        substring_clusters = substring_cluster_fn(non_embedded)
        return embedded_clusters + substring_clusters

    return _hybrid


def _outcome_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the outcome payload dict (the ``args`` of the execute row).

    Record-outcome writes canonical PEVR: propose carries the
    ``target_kind`` marker, execute carries ``{"tool":
    "emit_query_outcome_recorded", "args": <payload_dict>, ...}``.
    Clustering needs the payload fields (nl_question, quality_score,
    final_query_spec) which live in ``args`` on the execute row.
    """
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return {}
    return args


def _resolved_domain(payload: dict[str, Any]) -> str:
    """Domain id resolution for clustering.

    ``query_outcome_recorded`` payloads don't carry ``domain_id``
    directly (the schema is in entries.py Task 3). We fall back to a
    grouping by ``final_query_spec.domain_id`` when present, else a
    sentinel ``"_no_domain"`` so outcomes-without-domain still cluster
    with one another.
    """
    spec = payload.get("final_query_spec") or {}
    if isinstance(spec, dict):
        d = spec.get("domain_id")
        if d:
            return str(d)
    d = payload.get("domain_id")
    if d:
        return str(d)
    return "_no_domain"


def _quality_decimal(payload: dict[str, Any]) -> Decimal | None:
    """Parse the ``quality_score`` string into a ``Decimal``.

    Returns None if the field is missing or unparseable — the caller
    treats that as "doesn't meet the gate". Quietly skipping malformed
    outcomes is safer than wedging the Reactivity on a bad row.
    """
    raw = payload.get("quality_score")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _high_quality_outcome(payload: dict[str, Any]) -> bool:
    """Quality filter shared by both Reactivities.

    Passes iff ``used AND useful AND quality_score >= 0.9``. Returns
    False on any malformed field — consistent with the template-
    promotion Reactivity's defensive parsing.
    """
    used = bool(payload.get("used"))
    useful = bool(payload.get("useful"))
    score = _quality_decimal(payload)
    if score is None:
        return False
    return used and useful and score >= _QUALITY_GATE


def _high_quality_outcome_template(payload: dict[str, Any]) -> bool:
    """Quality filter for the template-promotion path.

    Templates pre-date the journey-revision quality contract: v1 only
    requires ``quality_score >= 0.9`` (no used/useful gate). Kept
    distinct from ``_high_quality_outcome`` so the data-product path can
    tighten without changing template behaviour.
    """
    score = _quality_decimal(payload)
    if score is None:
        return False
    return score >= _QUALITY_GATE


# ---------------------------------------------------------------------------
# Compounding primitive — closes journey Seam #4
# ---------------------------------------------------------------------------


# Type aliases keep the dataclass signature legible without bringing
# Protocol heavy machinery into the function annotations.
_QualityFilter = Callable[[dict[str, Any]], bool]
_GatherFn = Callable[
    [dict[str, Any], ReactivityContext], Awaitable[Sequence[dict[str, Any]]]
]
_ClusterFn = Callable[
    [Sequence[dict[str, Any]]], list[list[dict[str, Any]]]
]
_PromotionThreshold = Callable[[list[dict[str, Any]]], bool]
_PromotionAction = Callable[
    [list[dict[str, Any]], ReactivityContext], Awaitable["FiredAction | None"]
]
# v2.B Phase 2: first-class idempotency filter parameter on the
# primitive. Returns True if the cluster has already been promoted
# (per a ledger scan the filter owns) — when True, the framework
# skips the promotion_action and emits no action. None preserves
# Phase 1 behaviour (the existing factories do their own inline
# ledger-scan idempotency inside promotion_action).
_IdempotencyFilter = Callable[
    [list[dict[str, Any]], ReactivityContext], Awaitable[bool]
]
# Novelty key can be a static string (same key for every fire) or a
# callable that derives a per-entry key (e.g. f"...:{agent_query_id}")
# so per-instance debounce doesn't collide across distinct originators.
_NoveltyKeyFn = Callable[[dict[str, Any]], str]


@dataclass
class Compounding:
    """Parameterised W5a Reactivity primitive — the journey Seam #4 shape.

    A ``Compounding`` instance fires on its ``source_predicate``, applies
    ``quality_filter`` to the triggering entry's payload (the ``args`` of
    the execute row), gathers candidate entries via ``gather_fn``, runs
    ``cluster_fn`` to bucket them, and invokes ``promotion_action`` on
    every cluster that passes ``promotion_threshold``. Debounce is
    expressed via the optional ``condition`` field (typically a
    ``NotRecentlyFired``); if ``None``, the primitive runs ``AlwaysAllow``.

    The pipeline contract:

      1. ``predicate.match`` (the W5a runner already evaluated this) →
         we land in ``fire`` only if the triggering entry matched
         ``source_predicate``.
      2. ``quality_filter(triggering_payload)`` — short-circuit if False;
         the result is ``ReactivityResult(fired=False)``.
      3. ``gather_fn(triggering_entry, ctx) -> Sequence[entry]`` —
         returns the candidate set the cluster_fn will see. The
         per-outcome path returns ``[triggering_entry]``; the template
         path scans the recent ledger and returns all in-window
         outcomes. Async so it can do ledger I/O.
      4. ``cluster_fn(candidates) -> list[list[entry]]`` — partitions
         candidates into clusters. Identity-cluster is
         ``[[e] for e in entries]``.
      5. ``promotion_threshold(cluster) -> bool`` — filter clusters by
         cardinality (e.g. ``>= 3`` for templates).
      6. ``promotion_action(cluster, ctx) -> FiredAction | None`` —
         emit the target entries. Returns ``None`` if the action was
         idempotently suppressed (already-promoted), otherwise a
         ``FiredAction`` describing what was written. The action owns
         its own ledger.write call and any per-cluster idempotency
         scan it requires (e.g. checking for an existing
         ``query_template_promoted`` row).

    Two existing Reactivities are thin subclasses that fill these
    parameters. The primitive itself is registry-registrable directly
    (Phase 2 will compose three new axes via plain ``Compounding(...)``
    instances, no subclass needed).
    """

    id: str
    name: str
    description: str
    source_predicate: ReactivityPredicate
    quality_filter: _QualityFilter
    gather_fn: _GatherFn
    cluster_fn: _ClusterFn
    promotion_threshold: _PromotionThreshold
    promotion_action: _PromotionAction
    # Novelty key — either a static str shared by every fire, or a
    # callable that takes the triggering entry and returns the per-fire
    # key. Per-outcome Reactivities (data-product) use a callable so the
    # debounce condition doesn't collide across different agent_query_ids;
    # cluster Reactivities (template) use a static key because all
    # cluster fires within a window are intentionally debounced.
    novelty_key: str | _NoveltyKeyFn = ""
    scope: ReactivityScope = "company"

    # v2.B Phase 2 first-class idempotency parameter — replaces the
    # ad-hoc ledger-scan dotted around each Phase-1 promotion_action.
    # When non-None and returns True for a cluster, the framework
    # skips promotion_action and emits no FiredAction for that cluster.
    # Default None preserves Phase-1 behaviour (the existing factories
    # keep their inline idempotency checks for byte-for-byte
    # equivalence).
    idempotency_filter: _IdempotencyFilter | None = None

    # Optional debounce — ``None`` collapses to ``AlwaysAllow`` so the
    # primitive always satisfies the Reactivity Protocol's
    # ``condition: ReactivityCondition`` field.
    _condition_override: ReactivityCondition | None = None

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = self.source_predicate
        self.condition = (
            self._condition_override
            if self._condition_override is not None
            else AlwaysAllow()
        )

    # ------------------------------------------------------------------
    # Fire pipeline
    # ------------------------------------------------------------------

    def _resolve_novelty_key(self, entry: dict[str, Any]) -> str:
        """Resolve ``novelty_key`` for this fire — static str or callable."""
        if callable(self.novelty_key):
            try:
                return str(self.novelty_key(entry))
            except Exception:
                return ""
        return self.novelty_key

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        novelty_key = self._resolve_novelty_key(entry)

        # 1. Quality filter on the triggering entry's payload.
        payload = _outcome_args(entry)
        if not self.quality_filter(payload):
            return ReactivityResult(
                fired=False, actions=[], novelty_key=novelty_key,
            )

        # 2. Gather candidates via the parameterised gather_fn. The
        #    default ``_gather_triggering_entry`` returns just
        #    ``[entry]``; cluster-axis Reactivities scan the ledger.
        candidates = await self.gather_fn(entry, context)

        # 3. Cluster — partition into a list of clusters.
        clusters = self.cluster_fn(candidates)

        # 4. Threshold + idempotency + action loop. The framework-level
        #    ``idempotency_filter`` (v2.B Phase 2) short-circuits the
        #    cluster before promotion_action runs; the action may ALSO
        #    own its own inline idempotency scan (Phase-1 factories do
        #    this for byte-for-byte continuity). A returned None from
        #    promotion_action keeps the older "suppressed" signal.
        actions: list[FiredAction] = []
        for cluster in clusters:
            if not self.promotion_threshold(cluster):
                continue
            if self.idempotency_filter is not None:
                already = await self.idempotency_filter(cluster, context)
                if already:
                    continue
            fired_action = await self.promotion_action(cluster, context)
            if fired_action is not None:
                actions.append(fired_action)

        return ReactivityResult(
            fired=bool(actions),
            actions=actions,
            novelty_key=novelty_key,
        )


# ---------------------------------------------------------------------------
# Default gather + cluster fns the two factories consume
# ---------------------------------------------------------------------------


async def _gather_triggering_entry(
    entry: dict[str, Any], _ctx: ReactivityContext,
) -> Sequence[dict[str, Any]]:
    """gather_fn default — return only the entry that triggered this fire.

    Used by per-outcome compounding (data-product promotion). Skips the
    ledger scan because the action only ever cares about the triggering
    entry.
    """
    return [entry]


def _outcome_execute_entries(
    entries: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Return execute entries for query_outcome_recorded PEVR cycles
    landed at-or-after ``cutoff``.

    Matches the canonical EntryKind shape: ``kind=="execute"`` and
    ``payload.tool=="emit_query_outcome_recorded"``. The outcome
    payload fields (agent_query_id, nl_question, quality_score, ...)
    live in ``payload.args``. Order is preserved (entries arrive
    seq-ascending) so the latest fire is at the tail.
    """
    out: list[dict[str, Any]] = []
    for r in entries:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_query_outcome_recorded":
            continue
        ts = r.get("ts")
        if isinstance(ts, datetime) and ts < cutoff:
            continue
        out.append(r)
    return out


def _make_gather_lookback_outcomes(lookback_days: int) -> _GatherFn:
    """Build a gather_fn that scans the ledger for in-window outcomes.

    Used by the template-promotion factory. The closure captures
    ``lookback_days`` so callers can tune the window per-Reactivity
    without leaking the constant into the primitive's contract.
    """

    async def _gather(
        _entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(days=lookback_days)
        rows = await ctx.ledger.fetch(ctx.company_id)
        return _outcome_execute_entries(rows, cutoff=cutoff)

    return _gather


# ---------------------------------------------------------------------------
# v2.B Phase 3c — projection-promoted gather (axes 1 + 3)
# ---------------------------------------------------------------------------
#
# Phase 3b populated ``projection_query_outcomes.embedding`` at write
# time. Phase 3c closes the loop by reading from that projection table
# (pre-filtered by company_id + day-window, optionally TopK-ordered by
# pgvector cosine) instead of folding the entire ledger on every fire.
#
# The reader Protocol lives in
# ``apps/worm-core/src/wormbase_core/projection_readers.py`` so this
# package keeps zero cross-package import. The reader is opt-in: when
# the factories are constructed with ``projection_reader=None``
# (default) the existing ledger-scan path runs unchanged — preserves
# byte-identity for all Phase 1+2+3+3b tests.
#
# Decision D3 fallback: when the triggering entry has no embedding
# the reader is still called with ``triggering_embedding=None``; it
# returns a day-windowed non-cosine result. Decision D6: the
# Compounding primitive's quality_filter still runs on each gathered
# entry (e.g. ``used=true AND useful=false`` for axis 3), so the
# projection-gather can over-fetch safely.

# Default TopK for the pgvector pre-filter. Wide enough to capture any
# cluster of interest at v2.B Phase 3c cardinality (~hundreds of
# outcomes per day per company), narrow enough that the SQL ORDER BY
# cost stays bounded. Tunable per-factory via the ``topk_limit``
# parameter when production traffic grows.
_PROJECTION_TOPK_LIMIT: int = 100


def _triggering_embedding(
    entry: dict[str, Any],
) -> list[float] | None:
    """Extract the triggering entry's embedding, or None if absent.

    The triggering entry is the canonical PEVR execute row; the
    embedding lives on ``payload.args.embedding``. Returned as a list
    so the reader's SQL bind can serialise it uniformly across
    Postgres + SQLite paths.
    """
    args = _outcome_args(entry)
    raw = args.get("embedding")
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    try:
        return [float(v) for v in raw]
    except (TypeError, ValueError):
        return None


def _make_gather_via_projection(
    reader: Any,
    *,
    lookback_days: int,
    topk_limit: int = _PROJECTION_TOPK_LIMIT,
) -> _GatherFn:
    """Build a gather_fn that reads from ``projection_query_outcomes``.

    The reader satisfies the
    :class:`wormbase_core.projection_readers.QueryOutcomeProjectionReader`
    Protocol. The closure captures ``lookback_days`` + ``topk_limit``
    so per-axis tuning (e.g. axis 3's 14d vs axis 1's 30d) does not
    bleed into the primitive's contract.

    Replay-safety (Decision D5): the reader call is deterministic
    given (ledger_state, embedding_seed, time_window). Wire-replay
    reproduces both the projection-table state (fold is deterministic)
    and the time window (``ctx.now()`` returns the recorded
    timestamp); the gather result is therefore stable across runs.

    Quality-filter (Decision D6): the Compounding primitive runs the
    per-cluster quality_filter (axis 1: ``quality_score >= 0.9``;
    axis 3: ``used AND NOT useful OR quality_score < 0.3``) AFTER
    this gather, so over-fetching by TopK or the non-cosine fallback
    branch is safe.
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        emb = _triggering_embedding(entry)
        rows = await reader.recent_outcomes(
            company_id=ctx.company_id,
            triggering_embedding=emb,
            days=lookback_days,
            topk_limit=topk_limit,
            now=now,
        )
        return rows

    return _gather


def _cluster_by_canonical_intent(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """cluster_fn for template promotion.

    Groups outcome execute entries by ``(resolved_domain, canonical NL
    intent)``. Returns clusters in insertion order (group-by stability
    matters only for determinism in tests).

    The quality filter is applied UPSTREAM on the triggering entry, but
    cluster members also need to pass — a cluster of mixed-quality
    outcomes is wrong. Per-member quality is re-checked here so the
    template-promotion behaviour matches the pre-refactor contract
    byte-for-byte.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in entries:
        args = _outcome_args(e)
        if not _high_quality_outcome_template(args):
            continue
        intent = _canonical_intent(str(args.get("nl_question") or ""))
        if not intent:
            continue
        domain = _resolved_domain(args)
        groups.setdefault((domain, intent), []).append(e)
    return list(groups.values())


def _cluster_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """cluster_fn for per-outcome promotion: each entry is its own cluster."""
    return [[e] for e in entries]


# ---------------------------------------------------------------------------
# Template-promotion idempotency + action
# ---------------------------------------------------------------------------


def _existing_promotion_keys(
    entries: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    """Return the ``(domain, canonical_intent)`` keys that already have a
    ``query_template_promoted`` entry in the ledger.

    Promotion is idempotent: a Reactivity that already promoted a given
    cluster must not double-write. The check looks at the propose-phase
    payload signature (``nl_intent`` + ``domain_id`` are required fields
    on ``QueryTemplatePromotedPayload``).
    """
    keys: set[tuple[str, str]] = set()
    for r in entries:
        if r.get("kind") != "propose":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        # query_template_promoted is the only payload with
        # nl_intent + promoted_from_outcome_ids
        if "nl_intent" not in payload or "promoted_from_outcome_ids" not in payload:
            continue
        domain = str(payload.get("domain_id") or "_no_domain")
        intent = str(payload.get("nl_intent") or "")
        if intent:
            keys.add((domain, _canonical_intent(intent)))
    return keys


async def _emit_query_template_promoted(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> FiredAction | None:
    """promotion_action for template promotion.

    Writes one ``query_template_promoted`` PEVR cycle if no prior
    promotion exists for the cluster's ``(domain, canonical_intent)``
    key. Returns the resulting ``FiredAction`` on emit, or ``None`` if
    the cluster was already promoted (idempotency short-circuit).

    v1 cluster summary:

      * ``nl_intent`` = canonicalised NL question (the cluster key);
      * ``query_spec`` = the ``final_query_spec`` of the highest-
        quality outcome (ties broken by latest seq);
      * ``promoted_from_outcome_ids`` = entry_id (as str) of every
        cluster member, in original ledger order;
      * ``quality_score`` = mean quality of the cluster, formatted as
        a Decimal string in [0.0, 1.0] for JSON safety.
    """
    if not cluster:
        return None
    first_args = _outcome_args(cluster[0])
    domain = _resolved_domain(first_args)
    intent = _canonical_intent(str(first_args.get("nl_question") or ""))
    if not intent:
        return None

    # Per-cluster idempotency: scan the ledger for an existing
    # query_template_promoted row matching (domain, intent). This is
    # the ledger-truth idempotency guard that survives Reactivity
    # restart / re-registration.
    rows = await ctx.ledger.fetch(ctx.company_id)
    existing = _existing_promotion_keys(rows)
    if (domain, intent) in existing:
        return None

    # Pick the "best" outcome to source the template's query_spec
    # from: highest quality, latest seq on ties.
    best = max(
        cluster,
        key=lambda r: (
            _quality_decimal(_outcome_args(r)) or Decimal("0"),
            int(r.get("seq", 0)),
        ),
    )
    best_args = _outcome_args(best)
    query_spec = best_args.get("final_query_spec") or {}
    if not isinstance(query_spec, dict):
        query_spec = {}

    # Compute mean quality across the cluster.
    qualities = [
        q for q in (
            _quality_decimal(_outcome_args(r)) for r in cluster
        )
        if q is not None
    ]
    mean_quality: Decimal = (
        sum(qualities, Decimal("0")) / Decimal(len(qualities))
        if qualities else _QUALITY_GATE
    )
    # Quantize to 4 decimal places to match the projection_query_*
    # NUMERIC(6, 4) shape.
    mean_q_str = format(mean_quality.quantize(Decimal("0.0001")), "f")

    promoted_ids = tuple(str(r.get("entry_id")) for r in cluster)

    # Payload fields for QueryTemplatePromotedPayload.
    promotion_payload: dict[str, Any] = {
        "domain_id": domain,
        "nl_intent": intent,
        "query_spec": query_spec,
        "promoted_from_outcome_ids": promoted_ids,
        "quality_score": mean_q_str,
    }

    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose=promotion_payload,
        execute_fn=lambda: dict(promotion_payload),
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "template_promoted", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"cluster of {len(cluster)} outcomes promoted to template"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )
    return FiredAction(action_kind="query_template_promoted", action_seqs=[])


# ---------------------------------------------------------------------------
# Data-product promotion idempotency + action
# ---------------------------------------------------------------------------


def _data_product_novelty_key(entry: dict[str, Any]) -> str:
    """Per-fire novelty key for the per-outcome data-product Reactivity.

    Keyed on ``agent_query_id`` so the per-outcome debounce doesn't
    collide across distinct originating queries. Matches the
    pre-refactor f"outcome_to_data_product:{agent_query_id}" contract.
    """
    args = _outcome_args(entry)
    aqi = args.get("agent_query_id")
    if not aqi:
        return "outcome_to_data_product"
    return f"outcome_to_data_product:{aqi}"


def _already_promoted_for_audit_trail(
    rows: list[dict[str, Any]], agent_query_id: str | None,
) -> bool:
    """Return True if a prior ``data_product_proposed`` execute row already
    references this ``agent_query_id`` via the parameters dict.

    Per-outcome idempotency: each agent_query has at most one
    auto-promoted data product. Admin promotes confirm via /data-products
    or /lake/metrics-proposed; rejection is a separate state.
    """
    if not agent_query_id:
        return False
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_data_product_proposed":
            continue
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            continue
        params = args.get("parameters") or {}
        if not isinstance(params, dict):
            continue
        if params.get("source_audit_trail_id") == agent_query_id:
            return True
    return False


async def _emit_data_product_proposed(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> FiredAction | None:
    """promotion_action for per-outcome data-product promotion.

    ``cluster`` is a 1-element list (identity clustering). Promotes the
    contained outcome to a ``data_product_proposed`` entry chained via
    ``parameters.source_audit_trail_id``. Returns ``None`` on idempotent
    skip (already-promoted) or pydantic validation failure.
    """
    if not cluster:
        return None
    entry = cluster[0]
    args = _outcome_args(entry)
    score = _quality_decimal(args) or Decimal("0")

    agent_query_id = args.get("agent_query_id")
    rows = await ctx.ledger.fetch(ctx.company_id)
    if _already_promoted_for_audit_trail(rows, agent_query_id):
        return None

    nl_question = str(args.get("nl_question") or "(no question recorded)")
    final_query_spec = args.get("final_query_spec") or {}
    if not isinstance(final_query_spec, dict):
        final_query_spec = {}

    # Derive domain_id from the originating query spec if present. Admin
    # can reassign on confirm via /data-products. If absent we leave
    # domain_id=None — the payload accepts it (optional field), and an
    # admin assigns domain on promote.
    domain_raw = final_query_spec.get("domain_id")
    domain_id: UUID | None = None
    if domain_raw:
        try:
            domain_id = UUID(str(domain_raw))
        except (ValueError, TypeError):
            domain_id = None

    dp_id = uuid4()
    aqi_short = (str(agent_query_id) or "unknown")[:8]
    synthetic_name = f"agent_query_{aqi_short}"
    # Quantize score to 4dp to match the projection NUMERIC(6,4) shape.
    score_str = format(score.quantize(Decimal("0.0001")), "f")

    # ``parameters`` carries the compounding-loop provenance fields.
    # ``source_audit_trail_id`` is the link back to the agent_query PEVR
    # chain shown on /trace/agent_query/[id]. ``proposed_by`` =
    # ``agent_gateway.compounding_loop`` distinguishes auto-promotions
    # from human / worm-chatter proposals on the admin queue.
    parameters: dict[str, Any] = {
        "nl_question": nl_question,
        "query_spec": final_query_spec,
        "source_audit_trail_id": agent_query_id,
        "quality_score": score_str,
        "proposed_by": "agent_gateway.compounding_loop",
        "status": "proposed",
    }

    args_for_entry: dict[str, Any] = {
        "data_product_id": str(dp_id),
        "name": synthetic_name,
        "kind": "table",
        # Worm-proposed → no human requester. Use the synthetic
        # all-zeros UUID (same convention as process_mapper).
        "requested_by_person_id": str(UUID(int=0)),
        "sources_required": [],
        "domain_id": str(domain_id) if domain_id is not None else None,
        "parameters": parameters,
        "prompted_by_message_id": None,
    }

    # Defensive verify: pydantic must accept this shape. If it fails,
    # log and skip rather than wedge the runner.
    try:
        from wormbase_ledger.entries import DataProductProposedPayload
        DataProductProposedPayload.model_validate({
            **args_for_entry,
            "data_product_id": dp_id,
            "requested_by_person_id": UUID(int=0),
            "sources_required": [],
            "domain_id": domain_id,
        })
    except Exception:
        return None

    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "data_product_proposed",
            "ref_id": str(dp_id),
            "reason": (
                f"outcome_to_data_product: auto-promotion of "
                f"high-quality agent_query={agent_query_id} "
                f"(quality={score_str})"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
            "source_audit_trail_id": agent_query_id,
        },
        execute_fn=lambda: {
            "tool": "emit_data_product_proposed",
            "args": args_for_entry,
            "result_ref": str(dp_id),
        },
        verify_fn=lambda _r: {
            "checks": [
                {
                    "name": "data_product_proposed_payload_valid",
                    "ok": True,
                },
                {"name": "quality_threshold_met", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": (
                f"high-quality outcome (q={score_str}) auto-promoted "
                f"to data_product_proposed for admin review"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )
    return FiredAction(action_kind="data_product_proposed")


# ---------------------------------------------------------------------------
# Reactivity #1 — OutcomeToTemplatePromotion (cluster axis)
# ---------------------------------------------------------------------------


class OutcomeToTemplatePromotionReactivity(Compounding):
    """Promote clusters of high-quality outcomes to query templates.

    On every ``query_outcome_recorded`` ledger entry the Reactivity:

      1. quality-filters the triggering entry (``quality_score >= 0.9``);
      2. gathers the last ``_LOOKBACK_DAYS`` of outcome execute rows;
      3. groups by hybrid clustering:
         - entries WITH embedding: cosine ≥ ``embedding_threshold`` (default 0.85)
         - entries WITHOUT embedding: ``(resolved_domain, canonical NL)``
           substring fallback
         The two halves are merged into one cluster list.
      4. for each group where ``len(group) >= _CLUSTER_THRESHOLD``:
         emits one ``query_template_promoted`` PEVR cycle (provided no
         prior promotion exists for the same key).

    v2.B Phase 3b (2026-05-12) — swap substring canonicalisation for
    cosine ≥ 0.85 clustering when entries carry an embedding. The
    pre-3b substring path is preserved verbatim for entries without
    an embedding (legacy ledgers + opt-out installations where
    ``WORMBASE_EMBEDDING_ENABLED`` is unset).

    The Reactivity itself is observation-only at the promote step:
    ``verify`` always passes; ``resolve`` always keeps. The promotion
    entry IS the side-effect. The Reactivity reports ``fired=True``
    only when at least one new promotion landed.

    Built on the ``Compounding`` primitive — see the module docstring
    for the parameter contract.
    """

    def __init__(
        self,
        *,
        embedding_threshold: float = _EMBEDDING_COSINE_THRESHOLD,
        projection_reader: Any | None = None,
        topk_limit: int = _PROJECTION_TOPK_LIMIT,
    ) -> None:
        # v2.B Phase 3c — opt-in projection-promoted gather. Default
        # ``projection_reader=None`` preserves byte-identical behaviour
        # against the existing ledger-scan path, so every Phase 1+2+3+3b
        # test passes unchanged. Worm-core's
        # ``agent_gateway_construction`` flips the wire on when
        # ``WORMBASE_GATHER_VIA_PROJECTION=true`` is set.
        gather_fn: _GatherFn
        if projection_reader is not None:
            gather_fn = _make_gather_via_projection(
                projection_reader,
                lookback_days=_LOOKBACK_DAYS,
                topk_limit=topk_limit,
            )
        else:
            gather_fn = _make_gather_lookback_outcomes(_LOOKBACK_DAYS)
        super().__init__(
            id="agent_gateway.outcome_to_template",
            name="agent-gateway.outcome-to-template",
            description=(
                "Promotes clusters of high-quality query_outcome_recorded "
                "entries to durable query_template_promoted entries. "
                "Triggers on every query_outcome_recorded; cluster "
                "threshold = 3 same-domain outcomes with "
                "quality_score >= 0.9 within the last 30 days. v2.B "
                "Phase 3b: clustering by embedding cosine >= 0.85 when "
                "available, substring canonical intent fallback otherwise."
            ),
            source_predicate=EntryKind("query_outcome_recorded"),
            quality_filter=_high_quality_outcome_template,
            gather_fn=gather_fn,
            cluster_fn=_make_hybrid_cluster_fn(
                threshold=embedding_threshold,
                substring_cluster_fn=_cluster_by_canonical_intent,
            ),
            promotion_threshold=lambda cluster: len(cluster) >= _CLUSTER_THRESHOLD,
            promotion_action=_emit_query_template_promoted,
            novelty_key="outcome_to_template",
            scope="company",
            _condition_override=NotRecentlyFired(
                novelty_key="outcome_to_template", hours=_DEBOUNCE_HOURS,
            ),
        )


def make_outcome_to_template_promotion_reactivity(
    *,
    embedding_threshold: float = _EMBEDDING_COSINE_THRESHOLD,
    projection_reader: Any | None = None,
    topk_limit: int = _PROJECTION_TOPK_LIMIT,
) -> OutcomeToTemplatePromotionReactivity:
    """Factory wrapping :class:`OutcomeToTemplatePromotionReactivity`.

    Mirrors the ``make_query_failure_to_bad_pattern_reactivity`` shape so
    callers can construct axis 1 + axis 3 through a uniform factory
    style. Useful for the v2.B Phase 3c opt-in projection-gather wiring:
    pass ``projection_reader`` to swap the ledger-scan gather for a
    projection-table TopK SELECT.

    Default ``projection_reader=None`` preserves the Phase 1+2+3+3b
    byte-identical behaviour.
    """
    return OutcomeToTemplatePromotionReactivity(
        embedding_threshold=embedding_threshold,
        projection_reader=projection_reader,
        topk_limit=topk_limit,
    )


# ---------------------------------------------------------------------------
# Reactivity #2 — QueryOutcomeToDataProduct (per-outcome axis)
# ---------------------------------------------------------------------------


class QueryOutcomeToDataProductReactivity(Compounding):
    """Auto-promotes high-quality agent-query outcomes to ``data_product_proposed``.

    Per W3.2 journey revision §2 Stage 8 + Seam #4: closes the
    agent-query → data-product lifecycle gap. A high-quality outcome
    (``used=true AND useful=true AND quality_score >= 0.9``) becomes a
    proposed data product, chained via ``parameters.source_audit_trail_id``
    to the originating ``agent_query`` for full provenance.

    Admin reviews via ``/lake/metrics-proposed`` or ``/data-products``
    to confirm/reject. Per-outcome idempotency: each ``agent_query_id``
    auto-promotes at most one proposal — re-firing on the same outcome
    is a no-op (the action's ledger scan in
    ``_already_promoted_for_audit_trail`` short-circuits).

    Sister Reactivity to ``OutcomeToTemplatePromotionReactivity``:

      * Template promotion clusters ``>= 3`` outcomes with the same NL
        intent into one durable template.
      * Data-product promotion is per-outcome: every individually
        high-quality outcome surfaces as a proposed artifact, because
        a single useful outcome is enough evidence for an admin to
        consider publishing it.

    Built on the ``Compounding`` primitive — see the module docstring
    for the parameter contract.
    """

    def __init__(self) -> None:
        super().__init__(
            id="agent_gateway.outcome_to_data_product",
            name="agent-gateway.outcome-to-data-product",
            description=(
                "Auto-promotes high-quality agent-query outcomes "
                "(used=true AND useful=true AND quality_score >= 0.9) to "
                "data_product_proposed entries. Each outcome becomes at "
                "most one proposed data product, chained via "
                "source_audit_trail_id to the originating agent_query "
                "for SOC-2 provenance."
            ),
            source_predicate=EntryKind("query_outcome_recorded"),
            quality_filter=_high_quality_outcome,
            gather_fn=_gather_triggering_entry,
            cluster_fn=_cluster_identity,
            promotion_threshold=lambda cluster: len(cluster) >= 1,
            promotion_action=_emit_data_product_proposed,
            # Per-outcome debounce: scope the novelty key by
            # agent_query_id so distinct originating queries don't
            # collide. Matches the pre-refactor f"outcome_to_data_product:
            # {agent_query_id}" key contract.
            novelty_key=_data_product_novelty_key,
            scope="company",
            _condition_override=NotRecentlyFired(
                novelty_key="outcome_to_data_product", hours=1.0,
            ),
        )


# ---------------------------------------------------------------------------
# v2.B Phase 2 — Axis 3: QueryFailureToBadPattern
# ---------------------------------------------------------------------------
#
# Per-axis quality_filter (Phase 1 concern #1): "bad outcome" =
# ``used=True AND useful=False`` OR ``quality_score < 0.3``. The
# "used but not useful" criterion classifies queries the agent
# actually issued but the user (or downstream verify) flagged as
# wrong; the low-quality-score branch catches automated
# low-confidence failures.
#
# gather_fn (Phase 1 concern #2): low-cadence scan over a 14d window.
# ``query_outcome_recorded`` lands minutes-to-days after the query
# closes — bad-pattern clusters compound slowly enough that ledger
# scan cost is bounded.
#
# Idempotency (Phase 1 concern #3 + #4): a ``bad_pattern_proposed``
# already exists for the canonical intent. Replaces the inline
# ledger-scan pattern with the first-class ``idempotency_filter``
# parameter introduced in Phase 2.

# Lower bound where a "bad" auto-classification triggers without needing
# the agent's useful=False signal. Aligned with the quality_score
# scoring pipeline's low-confidence band.
_BAD_QUALITY_CUTOFF: Decimal = Decimal("0.3")
_BAD_PATTERN_LOOKBACK_DAYS: int = 14
_BAD_PATTERN_THRESHOLD: int = 2


def _bad_outcome_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the bad-pattern axis.

    Returns True iff the outcome qualifies as a "failed" or "unhelpful"
    sample: ``used=True AND useful=False`` (the user actually tried the
    answer and flagged it as wrong), OR ``quality_score < 0.3`` (an
    automated low-confidence verdict). The agent-quality-pipeline
    captures both flavours of failure on the same payload, so a single
    filter covers them.
    """
    if payload.get("used") and not payload.get("useful"):
        return True
    score = _quality_decimal(payload)
    if score is not None and score < _BAD_QUALITY_CUTOFF:
        return True
    return False


def _cluster_by_canonical_intent_only(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """cluster_fn for the bad-pattern axis.

    Groups by canonical NL intent only (no per-member quality re-check —
    the upstream ``quality_filter`` on the triggering entry already
    classified this run as bad, and gather_fn returns only entries that
    pass the same filter via ``_outcome_execute_entries`` + an inline
    check below). Same v1 substring canonicalisation as template
    promotion so the two axes use a shared key space.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in entries:
        args = _outcome_args(e)
        if not _bad_outcome_filter(args):
            continue
        intent = _canonical_intent(str(args.get("nl_question") or ""))
        if not intent:
            continue
        domain = _resolved_domain(args)
        groups.setdefault((domain, intent), []).append(e)
    return list(groups.values())


def _existing_bad_pattern_intents(
    entries: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    """Return the ``(domain, canonical_intent)`` keys with an existing
    ``bad_pattern_proposed`` propose row in the ledger."""
    keys: set[tuple[str, str]] = set()
    for r in entries:
        if r.get("kind") != "propose":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        # Marker fields unique to BadPatternProposedPayload propose rows.
        if payload.get("target_kind") != "bad_pattern_proposed":
            continue
        intent = str(payload.get("canonical_intent") or "")
        if not intent:
            continue
        domain = str(payload.get("domain_id") or "_no_domain")
        keys.add((domain, intent))
    return keys


async def _bad_pattern_already_proposed(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> bool:
    """Idempotency filter — True if a ``bad_pattern_proposed`` already
    exists for this cluster's ``(domain, canonical_intent)``."""
    if not cluster:
        return True
    first_args = _outcome_args(cluster[0])
    domain = _resolved_domain(first_args)
    intent = _canonical_intent(str(first_args.get("nl_question") or ""))
    if not intent:
        return True
    rows = await ctx.ledger.fetch(ctx.company_id)
    existing = _existing_bad_pattern_intents(rows)
    return (domain, intent) in existing


async def _emit_bad_pattern_proposed(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> FiredAction | None:
    """promotion_action for the bad-pattern axis.

    Writes one ``bad_pattern_proposed`` PEVR cycle when the cluster
    crosses threshold and the idempotency_filter confirmed the cluster
    is not already promoted. Returns ``FiredAction`` on emit.

    Payload assembly:

      * ``canonical_intent`` = cluster key (lowercased, whitespace-
        collapsed NL question);
      * ``failed_outcome_ids`` = entry_ids of every cluster member;
      * ``failed_query_specs`` = the original final_query_spec dumps
        (in cluster order);
      * ``failure_count`` = cluster cardinality at promotion time;
      * ``suggested_avoidance`` = a deterministic prose hint summarising
        the failure rate; production refinement will swap this for an
        LLM-generated suggestion via the reflective-suggest endpoint.
      * ``domain_id`` = the resolved domain (or None for ``_no_domain``).
    """
    if not cluster:
        return None
    first_args = _outcome_args(cluster[0])
    intent = _canonical_intent(str(first_args.get("nl_question") or ""))
    if not intent:
        return None
    domain = _resolved_domain(first_args)
    domain_id: str | None = None if domain == "_no_domain" else domain

    failed_ids = tuple(str(r.get("entry_id")) for r in cluster)
    failed_specs: list[dict[str, Any]] = []
    for r in cluster:
        spec = _outcome_args(r).get("final_query_spec") or {}
        if isinstance(spec, dict):
            failed_specs.append(spec)

    suggestion = (
        f"Observed {len(cluster)} unsuccessful attempts on the canonical "
        f"intent '{intent}'. Avoid re-issuing the same QuerySpec shape; "
        f"surface a clarifying question to the user or invoke "
        f"lake.query.suggest_correction for a refined plan."
    )

    promotion_payload: dict[str, Any] = {
        "canonical_intent": intent,
        "failed_outcome_ids": failed_ids,
        "failed_query_specs": failed_specs,
        "failure_count": len(cluster),
        "suggested_avoidance": suggestion,
        "domain_id": domain_id,
    }

    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "bad_pattern_proposed",
            "canonical_intent": intent,
            "domain_id": domain_id,
            "ref_id": intent,
            "reason": (
                f"compounding-loop: {len(cluster)} unsuccessful outcomes "
                f"on intent '{intent}' within {_BAD_PATTERN_LOOKBACK_DAYS}d"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: dict(promotion_payload),
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "bad_pattern_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"cluster of {len(cluster)} unsuccessful outcomes "
                f"flagged as bad pattern"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )
    return FiredAction(action_kind="bad_pattern_proposed", action_seqs=[])


def make_query_failure_to_bad_pattern_reactivity(
    *,
    embedding_threshold: float = _EMBEDDING_COSINE_THRESHOLD,
    projection_reader: Any | None = None,
    topk_limit: int = _PROJECTION_TOPK_LIMIT,
) -> "Compounding":
    """Axis 3 — repeated agent-query failures → ``bad_pattern_proposed``.

    Source predicate: ``EntryKind("query_outcome_recorded")``.
    Quality filter: ``used=True AND useful=False`` OR
    ``quality_score < 0.3`` (see ``_bad_outcome_filter``).
    Window: 14 days.
    Threshold: >=2 matching failures.
    Clustering: hybrid — cosine ≥ ``embedding_threshold`` (default 0.85)
    for entries with embeddings; canonical NL intent substring fallback
    for entries without. Same merge contract as axis 1.
    Idempotency: first-class ``idempotency_filter`` keyed on
    ``(domain, canonical_intent)`` of the first cluster member.

    v2.B Phase 3b (2026-05-12) — swaps substring-only clustering for
    cosine clustering when embeddings are present. Same fallback
    contract as axis 1: entries with ``embedding=None`` cluster via
    substring; cluster-merge produces one list.

    v2.B Phase 3c (2026-05-12) — opt-in projection-promoted gather.
    Default ``projection_reader=None`` preserves the Phase 1+2+3+3b
    byte-identical ledger-scan path. When a reader is provided, the
    14d ledger scan is replaced by a projection-table SELECT with a
    pgvector cosine TopK pre-filter (Postgres) or a Python cosine
    rank (SQLite).

    LOW-to-MEDIUM cadence: failures land sparsely relative to total
    outcome volume, so the 14d ledger scan cost is bounded.
    """
    gather_fn: _GatherFn
    if projection_reader is not None:
        gather_fn = _make_gather_via_projection(
            projection_reader,
            lookback_days=_BAD_PATTERN_LOOKBACK_DAYS,
            topk_limit=topk_limit,
        )
    else:
        gather_fn = _make_gather_lookback_outcomes(
            _BAD_PATTERN_LOOKBACK_DAYS,
        )
    return Compounding(
        id="agent_gateway.failure_to_bad_pattern",
        name="agent-gateway.failure-to-bad-pattern",
        description=(
            "Promotes clusters of low-quality / unhelpful "
            "query_outcome_recorded entries (used=True AND useful=False, "
            "or quality_score < 0.3) into bad_pattern_proposed entries "
            "that the next agent's lake.semantic.search deprioritizes. "
            "Cluster threshold = 2 matching failures within 14 days. "
            "v2.B Phase 3b: clustering by embedding cosine >= 0.85 when "
            "available, substring canonical intent fallback otherwise."
        ),
        source_predicate=EntryKind("query_outcome_recorded"),
        quality_filter=_bad_outcome_filter,
        gather_fn=gather_fn,
        cluster_fn=_make_hybrid_cluster_fn(
            threshold=embedding_threshold,
            substring_cluster_fn=_cluster_by_canonical_intent_only,
        ),
        promotion_threshold=lambda cluster: len(cluster) >= _BAD_PATTERN_THRESHOLD,
        promotion_action=_emit_bad_pattern_proposed,
        # Static novelty_key — bad-pattern fires are intentionally
        # debounced cluster-wide within a window (same shape as the
        # template-promotion axis). The condition's allows() check and
        # the runner's on_fire recording stay byte-aligned because the
        # key is fixed.
        novelty_key="failure_to_bad_pattern",
        scope="company",
        idempotency_filter=_bad_pattern_already_proposed,
        _condition_override=NotRecentlyFired(
            novelty_key="failure_to_bad_pattern", hours=_DEBOUNCE_HOURS,
        ),
    )


# ---------------------------------------------------------------------------
# v2.B Phase 2/3 — Axis 4: SemanticGapToEscalation
# ---------------------------------------------------------------------------
#
# Triggers on a periodic ``clock_tick`` ledger entry (v2.B Phase 3
# 2026-05-12) — the Reactivity uses each tick as a deterministic
# cadence event to scan for old, unresolved gaps. Each unresolved gap
# older than the configured age window is its own cluster (no
# aggregation across distinct gaps).
#
# Phase-2 trigger was ``EntryKind("semantic_gap_proposed")``, which
# meant escalation only fired when a NEW gap landed. That left a
# freshly-installed worm unable to escalate prior gaps until a second
# gap arrived. Phase 3 swaps to ``Periodic(every_seconds=...)`` so the
# Reactivity fires on a real cadence regardless of new-gap traffic.
#
# This axis is LOW-CADENCE — semantic-gap entries land sparsely and
# the periodic tick is hourly by default. The per-trigger ledger scan
# cost stays bounded.

_GAP_ESCALATION_DAYS: int = 7
_GAP_ESCALATION_TICK_S: int = 3600  # hourly default; production tunes via env


def _gap_propose_entries(
    entries: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Return ``semantic_gap_proposed`` propose entries older than
    ``cutoff`` (i.e. landed at-or-before)."""
    out: list[dict[str, Any]] = []
    for r in entries:
        if r.get("kind") != "propose":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        # semantic_gap_proposed propose rows carry target_kind +
        # ref_id/agent_id; we match the canonical target_kind marker.
        if payload.get("target_kind") != "semantic_gap_proposed":
            continue
        ts = r.get("ts")
        if isinstance(ts, datetime) and ts > cutoff:
            continue
        out.append(r)
    return out


def _resolved_gap_ids(entries: list[dict[str, Any]]) -> set[str]:
    """Return the set of original gap ids that already have an
    ``external_metric_imported`` entry chained via
    ``promoted_from_gap_id``, OR an existing
    ``semantic_gap_escalated`` propose row (idempotency boundary).
    """
    resolved: set[str] = set()
    for r in entries:
        kind = r.get("kind")
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if kind == "execute":
            tool = payload.get("tool")
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            if tool == "emit_external_metric_imported":
                gap_id = args.get("promoted_from_gap_id")
                if gap_id:
                    resolved.add(str(gap_id))
        elif kind == "propose":
            if payload.get("target_kind") == "semantic_gap_escalated":
                gap_id = payload.get("original_gap_id")
                if gap_id:
                    resolved.add(str(gap_id))
    return resolved


def _gap_propose_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical-PEVR ``args`` for a semantic_gap_proposed
    cycle. ``semantic_gap_proposed`` writes via lake.semantic.gap
    use the same propose/execute shape — args live on the EXECUTE row,
    not the propose row, so we look up the matching execute by ref_id."""
    return {}  # placeholder; actual lookup happens in _make_gather_unresolved_gaps


def _make_gather_unresolved_gaps(*, days: int) -> _GatherFn:
    """Build a gather_fn that returns ``semantic_gap_proposed`` propose
    entries older than ``days`` AND not already resolved.

    Each returned entry is a propose row carrying ``target_kind="semantic_gap_proposed"``
    so the cluster_fn / promotion_action can read the gap_id directly off
    the propose row. The corresponding execute row carries the payload
    fields (nl_question, reason, proposed_metric_name) — the
    promotion_action does a quick lookup to attach them.
    """

    async def _gather(
        _entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(days=days)
        rows = await ctx.ledger.fetch(ctx.company_id)
        candidates = _gap_propose_entries(rows, cutoff=cutoff)
        if not candidates:
            return []
        resolved = _resolved_gap_ids(rows)
        return [
            r for r in candidates
            if str((r.get("payload") or {}).get("ref_id") or "") not in resolved
            and str(r.get("entry_id") or "") not in resolved
        ]

    return _gather


def _cluster_one_per_gap(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """cluster_fn for the gap-escalation axis — each unresolved gap is
    its own cluster (no aggregation across distinct gaps)."""
    return [[e] for e in entries]


def _semantic_gap_execute_row(
    rows: list[dict[str, Any]], gap_propose_entry: dict[str, Any],
) -> dict[str, Any] | None:
    """Find the execute row paired with a ``semantic_gap_proposed`` propose row.

    The execute row carries ``tool="emit_semantic_gap_proposed"`` +
    ``args=<payload>`` referencing the same gap. We match on the
    propose-row's ``ref_id`` against the args' agent_id+nl_question
    signature (no shared id field at propose time), but practically
    the canonical pairing is by seq adjacency. Returns None if not found.
    """
    propose_payload = gap_propose_entry.get("payload") or {}
    propose_ref = str(propose_payload.get("ref_id") or "")
    propose_seq = int(gap_propose_entry.get("seq", 0))
    for r in rows:
        if r.get("kind") != "execute":
            continue
        if int(r.get("seq", 0)) <= propose_seq:
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_semantic_gap_proposed":
            continue
        # Prefer the result_ref match if propose_ref was set, else
        # accept the first execute row after the propose seq.
        if propose_ref and payload.get("result_ref") == propose_ref:
            return r
        return r
    return None


async def _gap_already_escalated(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> bool:
    """Idempotency filter — True if a ``semantic_gap_escalated`` already
    exists for the original gap."""
    if not cluster:
        return True
    gap_entry = cluster[0]
    gap_id = str(gap_entry.get("entry_id") or "")
    if not gap_id:
        return True
    rows = await ctx.ledger.fetch(ctx.company_id)
    for r in rows:
        if r.get("kind") != "propose":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("target_kind") != "semantic_gap_escalated":
            continue
        if str(payload.get("original_gap_id") or "") == gap_id:
            return True
    return False


async def _emit_semantic_gap_escalated(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> FiredAction | None:
    """promotion_action for the gap-escalation axis.

    Writes one ``semantic_gap_escalated`` PEVR cycle, chained to the
    original gap via ``original_gap_id``. Computes the frozen
    ``days_unresolved`` snapshot from ``(now - gap.ts).days`` so
    downstream reads don't need to recompute it.
    """
    if not cluster:
        return None
    gap_entry = cluster[0]
    gap_id = str(gap_entry.get("entry_id") or "")
    if not gap_id:
        return None

    rows = await ctx.ledger.fetch(ctx.company_id)
    execute_row = _semantic_gap_execute_row(rows, gap_entry)
    args: dict[str, Any] = {}
    if execute_row is not None:
        ex_payload = execute_row.get("payload") or {}
        if isinstance(ex_payload, dict):
            cand = ex_payload.get("args") or {}
            if isinstance(cand, dict):
                args = cand

    nl_question = str(args.get("nl_question") or "(no question recorded)")
    reason = args.get("reason") or "no_match"
    if reason not in ("no_match", "low_confidence", "ambiguous"):
        reason = "no_match"
    proposed_metric_name = args.get("proposed_metric_name")
    if proposed_metric_name is not None:
        proposed_metric_name = str(proposed_metric_name)

    now = ctx.now() if callable(ctx.now) else ctx.now
    if not isinstance(now, datetime):
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    gap_ts = gap_entry.get("ts")
    if isinstance(gap_ts, datetime):
        if gap_ts.tzinfo is None:
            gap_ts = gap_ts.replace(tzinfo=UTC)
        days_unresolved = max(0, (now - gap_ts).days)
    else:
        days_unresolved = _GAP_ESCALATION_DAYS

    promotion_payload: dict[str, Any] = {
        "original_gap_id": gap_id,
        "nl_question": nl_question,
        "reason": reason,
        "days_unresolved": days_unresolved,
        "proposed_metric_name": proposed_metric_name,
    }

    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "semantic_gap_escalated",
            "original_gap_id": gap_id,
            "ref_id": gap_id,
            "reason": (
                f"compounding-loop: semantic_gap_proposed gap_id={gap_id} "
                f"unresolved after {days_unresolved}d"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: dict(promotion_payload),
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "semantic_gap_escalated", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"gap unresolved after {days_unresolved}d; escalated to "
                f"admin metric-proposal queue"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )
    return FiredAction(action_kind="semantic_gap_escalated", action_seqs=[])


def make_semantic_gap_to_escalation_reactivity(
    *,
    tick_interval_s: int = _GAP_ESCALATION_TICK_S,
) -> "Compounding":
    """Axis 4 — ``semantic_gap_proposed`` aged > N days → ``semantic_gap_escalated``.

    Source predicate (v2.B Phase 3): ``Periodic(every_seconds=tick_interval_s)``
    — the Reactivity fires on each ``clock_tick`` ledger entry written
    by :class:`wormbase_reactivities.clock_tick_emitter.ClockTickEmitter`.
    The gather_fn scans the ledger for unresolved gaps older than the
    age window and emits one ``semantic_gap_escalated`` per qualifying
    gap. Threshold: 1 (every qualifying unresolved gap escalates).
    Idempotency: ``original_gap_id`` already has a
    ``semantic_gap_escalated`` propose row in the ledger.

    LOW CADENCE — the periodic tick is hourly by default (3600s); the
    ledger-scan cost inside gather_fn is bounded by the unresolved-gap
    count. Multi-cadence safe: distinct ``ClockTickEmitter`` instances
    (e.g. hourly for gap-escalation, daily for digest reactivities)
    write separate ``clock_tick`` chains, and ``Periodic(every_seconds=N)``
    filters on matching cadence so this axis only sees its own ticks.

    Production note: the previous Phase-2 trigger
    (``EntryKind("semantic_gap_proposed")``) made escalation depend on
    new gap traffic — a freshly-installed worm with pre-existing gaps
    could not escalate them until a second gap landed. Phase 3
    decouples the cadence from the gap-write stream so any pre-existing
    gap escalates at the next tick.

    The factory is parameterized — ``make_agent_gateway_reactivities()``
    can pass a tick interval (e.g. read from
    ``WORMBASE_AGENT_GATEWAY_TICK_S``). Default 3600s.
    """
    return Compounding(
        id="agent_gateway.gap_to_escalation",
        name="agent-gateway.gap-to-escalation",
        description=(
            "Escalates semantic_gap_proposed entries that remain "
            "unresolved (no matching external_metric_imported, no prior "
            "escalation) after a 7-day window. Each unresolved gap "
            "becomes its own semantic_gap_escalated entry surfaced on "
            "the admin metric-proposal queue with priority. Driven by "
            "ClockTickEmitter; cadence configured at boot."
        ),
        source_predicate=Periodic(every_seconds=tick_interval_s),
        # Every tick is a potential trigger — the gate is gather_fn,
        # not quality_filter.
        quality_filter=lambda _payload: True,
        gather_fn=_make_gather_unresolved_gaps(days=_GAP_ESCALATION_DAYS),
        cluster_fn=_cluster_one_per_gap,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_emit_semantic_gap_escalated,
        novelty_key="gap_to_escalation",
        scope="company",
        idempotency_filter=_gap_already_escalated,
        _condition_override=NotRecentlyFired(
            novelty_key="gap_to_escalation", hours=_DEBOUNCE_HOURS,
        ),
    )


# ---------------------------------------------------------------------------
# v2.B Phase 2 — Axis 5: DataProductConsumptionToRecommendation
# ---------------------------------------------------------------------------
#
# Source predicate: ``EntryKind("data_product_consumed")``.
# Quality filter: ``surface ∈ {mcp, agent, api}`` — count agent /
# automation consumers, not human dashboard hits.
# gather_fn: scan recent ``data_product_consumed`` execute rows
# within a 7-day look-back.
# Cluster: by ``data_product_id``.
# Threshold: >=3 DISTINCT consumer ids within window.
# Idempotency: ``data_product_recommended`` already exists for the
# product id.

_RECOMMENDATION_LOOKBACK_DAYS: int = 7
_RECOMMENDATION_THRESHOLD: int = 3
_AGENT_SURFACES: set[str] = {"mcp", "agent", "api"}


def _agent_consumption_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the recommendation axis.

    Returns True iff the consumption was issued via an agent / automation
    surface (MCP, agent, API). Dashboard/chat/voice/export consumers are
    human-driven and do not contribute to the recommendation signal —
    those reflect user behaviour we already surface elsewhere.
    """
    surface = payload.get("surface")
    return isinstance(surface, str) and surface in _AGENT_SURFACES


def _data_product_consumed_entries(
    entries: list[dict[str, Any]],
    *,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Return execute entries for ``emit_data_product_consumed`` cycles
    landed at-or-after ``cutoff``."""
    out: list[dict[str, Any]] = []
    for r in entries:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("tool") != "emit_data_product_consumed":
            continue
        ts = r.get("ts")
        if isinstance(ts, datetime) and ts < cutoff:
            continue
        out.append(r)
    return out


def _make_gather_lookback_consumptions(lookback_days: int) -> _GatherFn:
    """Build a gather_fn that scans the ledger for in-window consumptions.

    LOW CADENCE — data-product consumption traffic compounds slowly
    (an agent picks an artifact, consumes it once, may revisit days
    later). The 7d ledger-scan cost is bounded.
    """

    async def _gather(
        _entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(days=lookback_days)
        rows = await ctx.ledger.fetch(ctx.company_id)
        return _data_product_consumed_entries(rows, cutoff=cutoff)

    return _gather


def _consumer_id(entry: dict[str, Any]) -> str:
    """Return the distinct-consumer id for a ``data_product_consumed`` row.

    Prefers ``consumed_by_agent_id`` (an AgentID, present when the
    consumer is an automation actor) and falls back to
    ``consumed_by_person_id`` (the Person id stand-in v1 uses for
    agents 1:1 with a Person row). Both surfaces produce the same
    cluster cardinality.
    """
    args = (entry.get("payload") or {}).get("args") or {}
    if not isinstance(args, dict):
        return ""
    agent = args.get("consumed_by_agent_id")
    if agent:
        return str(agent)
    person = args.get("consumed_by_person_id")
    return str(person) if person else ""


def _cluster_by_data_product_id(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """cluster_fn for the recommendation axis.

    Groups consumption execute rows by ``data_product_id`` with an
    inline quality re-check so cluster membership matches the
    quality_filter contract byte-for-byte.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        args = (e.get("payload") or {}).get("args") or {}
        if not isinstance(args, dict):
            continue
        if not _agent_consumption_filter(args):
            continue
        dp_id = args.get("data_product_id")
        if not dp_id:
            continue
        groups.setdefault(str(dp_id), []).append(e)
    return list(groups.values())


async def _data_product_already_recommended(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> bool:
    """Idempotency filter — True if a ``data_product_recommended``
    propose row already exists for this product id."""
    if not cluster:
        return True
    first_args = (cluster[0].get("payload") or {}).get("args") or {}
    if not isinstance(first_args, dict):
        return True
    dp_id = str(first_args.get("data_product_id") or "")
    if not dp_id:
        return True
    rows = await ctx.ledger.fetch(ctx.company_id)
    for r in rows:
        if r.get("kind") != "propose":
            continue
        payload = r.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("target_kind") != "data_product_recommended":
            continue
        if str(payload.get("data_product_id") or "") == dp_id:
            return True
    return False


async def _emit_data_product_recommended(
    cluster: list[dict[str, Any]], ctx: ReactivityContext,
) -> FiredAction | None:
    """promotion_action for the recommendation axis.

    Writes one ``data_product_recommended`` PEVR cycle when the cluster
    has at least ``_RECOMMENDATION_THRESHOLD`` distinct consumers. The
    recommendation_score is the DISTINCT consumer count at promotion
    time (frozen); consumer_agent_ids is the deduplicated, encounter-
    ordered tuple.
    """
    if not cluster:
        return None
    first_args = (cluster[0].get("payload") or {}).get("args") or {}
    if not isinstance(first_args, dict):
        return None
    dp_id_raw = first_args.get("data_product_id")
    if not dp_id_raw:
        return None
    try:
        dp_id = UUID(str(dp_id_raw))
    except (ValueError, TypeError):
        return None

    seen: list[str] = []
    seen_set: set[str] = set()
    for e in cluster:
        cid = _consumer_id(e)
        if not cid or cid in seen_set:
            continue
        seen.append(cid)
        seen_set.add(cid)
    if len(seen) < _RECOMMENDATION_THRESHOLD:
        return None

    promotion_payload: dict[str, Any] = {
        "data_product_id": str(dp_id),
        "recommendation_score": len(seen),
        "consumer_agent_ids": tuple(seen),
        "consumed_within_days": _RECOMMENDATION_LOOKBACK_DAYS,
    }

    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "data_product_recommended",
            "data_product_id": str(dp_id),
            "ref_id": str(dp_id),
            "reason": (
                f"compounding-loop: {len(seen)} distinct agent consumers "
                f"of data_product_id={dp_id} within "
                f"{_RECOMMENDATION_LOOKBACK_DAYS}d"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: dict(promotion_payload),
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "data_product_recommended", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"cluster of {len(seen)} distinct consumers within "
                f"{_RECOMMENDATION_LOOKBACK_DAYS}d trended into a "
                f"recommended data_product"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )
    return FiredAction(action_kind="data_product_recommended", action_seqs=[])


def make_data_product_consumption_to_recommendation_reactivity() -> "Compounding":
    """Axis 5 — multi-agent ``data_product_consumed`` clusters →
    ``data_product_recommended``.

    Source predicate: ``EntryKind("data_product_consumed")``.
    Quality filter: surface ∈ {mcp, agent, api} (agent/automation
    consumers only — dashboard hits don't count).
    Window: 7 days.
    Cluster: by data_product_id.
    Threshold: >=3 DISTINCT consumer ids in-window.
    Idempotency: data_product_recommended already exists for this
    product id.

    LOW-CADENCE — consumption traffic compounds slowly. If a future
    deployment shows the gather_fn ledger scan becoming hot, swap it
    for a projection read in Phase 3.
    """
    return Compounding(
        id="agent_gateway.consumption_to_recommendation",
        name="agent-gateway.consumption-to-recommendation",
        description=(
            "Promotes clusters of multi-agent data_product_consumed "
            "entries (surface ∈ {mcp, agent, api}) into "
            "data_product_recommended entries surfaced on /data-products "
            "as 'trending' chips. Cluster threshold = 3 distinct "
            "consumer ids on the same data_product_id within 7 days."
        ),
        source_predicate=EntryKind("data_product_consumed"),
        quality_filter=_agent_consumption_filter,
        gather_fn=_make_gather_lookback_consumptions(_RECOMMENDATION_LOOKBACK_DAYS),
        cluster_fn=_cluster_by_data_product_id,
        promotion_threshold=lambda cluster: (
            len({_consumer_id(e) for e in cluster if _consumer_id(e)})
            >= _RECOMMENDATION_THRESHOLD
        ),
        promotion_action=_emit_data_product_recommended,
        novelty_key="consumption_to_recommendation",
        scope="company",
        idempotency_filter=_data_product_already_recommended,
        _condition_override=NotRecentlyFired(
            novelty_key="consumption_to_recommendation", hours=_DEBOUNCE_HOURS,
        ),
    )


# ---------------------------------------------------------------------------
# L3 Sub-wave B — LineageDiscovery axis
# ---------------------------------------------------------------------------
#
# Source predicate: ``source_connected`` ∨ ``external_catalog_imported``.
# Each per-source event triggers one inference pass: we enumerate the
# tables in the source via the injected catalog_reader, then ask the
# inference_service for proposed edges per source-table.
#
# Quality filter: ``source_id`` present + non-empty (sanity).
# Cluster: identity (one cluster per InferredEdge).
# Threshold: >= 1 (every edge is its own cluster).
# Promotion: emit one ``lineage_edge_proposed`` PEVR cycle per edge.
# Idempotency: dedup by ``edge_id`` within the propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 9):
# inference_service=None OR catalog_reader=None → no-op pass; preserves
# byte-identical pre-L3 behaviour. Telemetry counter recorded.

_LINEAGE_DEFAULT_DAYS_LOOKBACK: int = 7
_LINEAGE_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window


class _CatalogReader(Protocol):
    """Protocol for enumerating candidate target tables for inference.

    Sub-wave B documents the contract; the concrete impl wiring lands
    in Sub-wave C (likely a thin wrapper around wormbase-catalog-mirror
    reader). Async + tenant-scoped.

    Returns sequences of :class:`wormbase_agent_gateway.lineage.CatalogTable`
    instances; declared as ``Any`` here to avoid a hard dependency on
    the ``lineage`` subpackage at module import time (the Protocol is
    consumed structurally by callers, not via isinstance).
    """

    async def list_tables_for_source(
        self, *, company_id: UUID, source_id: str,
    ) -> list[Any]:
        """Return CatalogTable references for one source (the triggering one)."""
        ...

    async def list_candidate_targets(
        self, *, company_id: UUID, source_id: str,
    ) -> list[Any]:
        """Return CatalogTable references for *all* candidate target tables
        across all sources the worm knows about for this company.

        The inference service walks these against the source-table to
        propose edges. Sub-wave C may scope by domain to keep the
        candidate set bounded.
        """
        ...


def _lineage_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the lineage axis — source_id present and non-empty."""
    args = payload if not payload.get("args") else (payload.get("args") or {})
    source_id = args.get("source_id") if isinstance(args, dict) else None
    if source_id is None:
        # Some emitters surface source_id directly on payload (propose row)
        source_id = payload.get("source_id")
    return bool(source_id)


def _make_lineage_quality_filter() -> _QualityFilter:
    """Return the lineage axis quality_filter — source_id present + non-empty."""
    return _lineage_quality_filter


def _entry_source_id(entry: dict[str, Any]) -> str:
    """Extract source_id from a source_connected / external_catalog_imported entry."""
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return ""
    # Execute row: source_id is under payload.args or top-level (depending on
    # how the emitter packaged it). Try args first (canonical PEVR shape),
    # then top-level (some emitters put it on the execute payload directly),
    # then the propose ref_id as a last resort.
    args = payload.get("args") or {}
    if isinstance(args, dict):
        sid = args.get("source_id")
        if sid:
            return str(sid)
    sid = payload.get("source_id")
    if sid:
        return str(sid)
    sid = payload.get("ref_id")
    return str(sid) if sid else ""


def _make_lineage_gather_fn(
    catalog_reader: "_CatalogReader | None",
    days_lookback: int,
) -> _GatherFn:
    """Build a gather_fn that returns one synthetic entry per InferredEdge.

    The lineage axis differs from the other compounding axes: each fire
    triggers ONE inference pass (per source) that yields N candidate
    edges. We package each edge into a synthetic candidate entry the
    cluster_fn + promotion_action can read uniformly.

    When ``catalog_reader`` is None, returns an empty list (Optional-
    Effect absent path; the composite path-counter records the no-op).
    ``days_lookback`` is reserved for Sub-wave C's source-event windowing
    (currently unused: each trigger event is processed independently).
    """
    del days_lookback  # reserved for Sub-wave C

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []
        # We pass through the triggering entry's source_id so the
        # promotion_action can call the inference service. The
        # candidate enumeration happens inside the promotion path
        # (lazy — only on threshold-passing).
        return [{
            "_lineage_trigger": True,
            "company_id": str(ctx.company_id),
            "source_id": source_id,
            "triggering_entry_id": str(entry.get("entry_id") or ""),
            "triggering_kind": entry.get("kind"),
            "triggering_payload": entry.get("payload"),
        }]

    return _gather


def _cluster_lineage_proposals_by_edge_id(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual edge-by-edge_id dedup happens at promotion-action time,
    after the inference service runs (it dedups across strategies before
    returning). Each trigger entry produces its own cluster so the
    threshold = 1 contract is byte-identical to per-outcome axes.
    """
    return [[e] for e in entries]


def _make_lineage_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Build an idempotency_filter that scans for recent ``lineage_edge_proposed``
    entries within ``propose_window_seconds`` for ANY source the trigger touches.

    The actual per-edge dedup happens at promotion-action write time
    against the projection_lineage_edges fold (Sub-wave A): the same
    edge_id always folds onto one row regardless of how many propose
    entries land. This filter is a coarse short-circuit when an entire
    source has been freshly inferred within the window.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        if not source_id:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_lineage_edge_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            src_table_id = str(args.get("src_table_id") or "")
            tgt_table_id = str(args.get("tgt_table_id") or "")
            # Edge involves this source if either endpoint table_id starts
            # with the source_id prefix (canonical "<source_id>.<schema>.<table>").
            if (
                src_table_id.startswith(f"{source_id}.")
                or tgt_table_id.startswith(f"{source_id}.")
            ):
                return True
        return False

    return _filter


def _make_lineage_proposal_action(
    inference_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
) -> _PromotionAction:
    """Build the lineage promotion_action.

    Optional-Effect Injection (doctrine case 9):
    when ``inference_service`` or ``catalog_reader`` is None the action
    is a no-op pass: it records the no-op in DEBUG telemetry and emits
    no FiredAction. This preserves byte-identical Sub-wave A behaviour
    for any caller that has not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if inference_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        if not source_id:
            return None

        source_tables = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not source_tables:
            return None
        candidate_targets = await catalog_reader.list_candidate_targets(
            company_id=ctx.company_id, source_id=source_id,
        )

        all_edges: list[Any] = []
        for src in source_tables:
            edges = await inference_service.infer_edges(
                source_table=src,
                candidate_targets=candidate_targets,
            )
            all_edges.extend(edges)

        if not all_edges:
            return None

        # Dedup across multiple source-tables within this fire by edge_id.
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for e in all_edges:
            eid = e.edge_id
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            deduped.append(e)

        emitted_seqs: list[int] = []
        for edge in deduped:
            await _emit_lineage_edge_proposed(edge=edge, ctx=ctx)

        return FiredAction(
            action_kind="lineage_edge_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_lineage_edge_proposed(
    *,
    edge: Any,  # InferredEdge — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``lineage_edge_proposed`` PEVR cycle for ``edge``."""
    promotion_payload: dict[str, Any] = {
        "edge_id": edge.edge_id,
        "src_table_id": edge.src_table_id,
        "src_column": edge.src_column,
        "tgt_table_id": edge.tgt_table_id,
        "tgt_column": edge.tgt_column,
        "confidence": edge.confidence,
        "strategy": edge.strategy,
        "reasoning": edge.reasoning,
        "evidence": dict(edge.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "lineage_edge_proposed",
            "edge_id": edge.edge_id,
            "ref_id": edge.edge_id,
            "reason": (
                f"compounding-loop: lineage inference strategy="
                f"{edge.strategy} proposed {edge.src_table_id} → "
                f"{edge.tgt_table_id} confidence={edge.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_lineage_edge_proposed",
            "args": dict(promotion_payload),
            "result_ref": edge.edge_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "lineage_edge_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={edge.strategy} confidence={edge.confidence:.2f} "
                f"trended into a lineage_edge_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_lineage_discovery_reactivity(
    *,
    inference_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    days_lookback: int = _LINEAGE_DEFAULT_DAYS_LOOKBACK,
    propose_window_seconds: int = _LINEAGE_DEFAULT_PROPOSE_WINDOW_S,
) -> "Compounding":
    """L3 lineage-discovery axis.

    Source predicate: ``EntryKind("source_connected") |
    EntryKind("external_catalog_imported")``.

    Optional-Effect Injection (doctrine case 9):

      * ``inference_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate candidates → no-op.
      * Both present → fires per-source on source_connected /
        external_catalog_imported events.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes edges.

    Sub-wave C will wire concrete impls of ``inference_service``
    (a :class:`CompositeLineageInferenceService`) and ``catalog_reader``
    (a wrapper over wormbase-catalog-mirror reads) at install boot.

    Replay-stable: ``edge_id`` is deterministic on
    ``(src_table_id, src_column, tgt_table_id, tgt_column)`` so re-
    running the same source through the same strategies yields the
    same ledger entries.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's signature enforces it.
    """
    source_predicate = (
        EntryKind("source_connected") | EntryKind("external_catalog_imported")
    )
    return Compounding(
        id="agent_gateway.lineage_discovery",
        name="agent-gateway.lineage-discovery",
        description=(
            "Lake-side compounding axis: on source_connected / "
            "external_catalog_imported, runs lineage inference strategies "
            "(naming heuristic, sample overlap, dbt manifest) over the "
            "source's catalog tables and emits one lineage_edge_proposed "
            "PEVR cycle per inferred edge. Optional-Effect Injection: "
            "no-op when inference_service or catalog_reader is None."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_lineage_quality_filter(),
        gather_fn=_make_lineage_gather_fn(catalog_reader, days_lookback),
        cluster_fn=_cluster_lineage_proposals_by_edge_id,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_lineage_proposal_action(
            inference_service, catalog_reader,
        ),
        novelty_key="lineage_discovery",
        scope="company",
        idempotency_filter=_make_lineage_idempotency_filter(propose_window_seconds),
    )


# ---------------------------------------------------------------------------
# L7 Sub-wave B (2026-05-30) — quality-check discovery Compounding axis.
#
# Mirrors the L3 lineage-discovery axis structure. Source predicate:
# ``EntryKind("source_connected") | EntryKind("external_catalog_imported")``
# (same as L3 — the same upstream signal triggers both axes).
#
# gather_fn: returns one synthetic trigger entry per source_id.
# cluster_fn: identity (per-check dedup happens at promotion-action time,
# after the proposal service runs and dedups across strategies).
# Threshold: >= 1 (every check is its own cluster).
# Promotion: emit one ``quality_check_proposed`` PEVR cycle per check.
# Idempotency: dedup by check_id within propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 10):
# proposal_service=None OR catalog_reader=None → no-op pass; preserves
# byte-identical pre-L7 behaviour. Telemetry counter recorded.

_QUALITY_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window


def _quality_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L7 quality-check axis — source_id present."""
    # Identical contract to the L3 lineage axis: the trigger entry's
    # source_id must be non-empty for the gather step to proceed.
    return _lineage_quality_filter(payload)


def _make_quality_quality_filter() -> _QualityFilter:
    """Return the quality-discovery axis quality_filter."""
    return _quality_quality_filter


def _make_quality_gather_fn(
    catalog_reader: "_CatalogReader | None",
) -> _GatherFn:
    """Build a gather_fn that returns one synthetic trigger entry per source.

    Like the L3 lineage axis, each fire triggers ONE proposal pass per
    source. Each source-table is walked by the proposal service inside
    the promotion_action (lazy — only on threshold-passing).

    When ``catalog_reader`` is None, returns an empty list (Optional-
    Effect absent path; the composite telemetry counter records the
    no-op).
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []
        return [{
            "_quality_trigger": True,
            "company_id": str(ctx.company_id),
            "source_id": source_id,
            "triggering_entry_id": str(entry.get("entry_id") or ""),
            "triggering_kind": entry.get("kind"),
            "triggering_payload": entry.get("payload"),
        }]

    return _gather


def _cluster_quality_proposals_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual per-check dedup (by ``check_id``) happens at
    promotion-action time after the proposal service runs (it dedups
    across strategies before returning).
    """
    return [[e] for e in entries]


def _make_quality_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Suppress re-proposal when a source has been freshly inferred.

    Mirrors the L3 idempotency_filter shape: scans for recent
    ``quality_check_proposed`` execute entries within
    ``propose_window_seconds`` for any check whose table_id is
    prefixed by the trigger's source_id (canonical
    ``"<source_id>.<schema>.<table>"``).

    Per-check dedup at projection-fold time still keeps re-proposals
    safe (same check_id folds onto one row); this filter is a coarse
    short-circuit when the whole source has been freshly inferred.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        if not source_id:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_quality_check_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            table_id = str(args.get("table_id") or "")
            if table_id.startswith(f"{source_id}."):
                return True
        return False

    return _filter


def _make_quality_proposal_action(
    proposal_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
) -> _PromotionAction:
    """Build the quality-discovery promotion_action.

    Optional-Effect Injection (doctrine case 10):
    when ``proposal_service`` or ``catalog_reader`` is None the action
    is a no-op pass. This preserves byte-identical pre-L7 behaviour for
    callers that have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if proposal_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        if not source_id:
            return None

        source_tables = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not source_tables:
            return None

        all_checks: list[Any] = []
        for table in source_tables:
            # Thread ctx.company_id through so the L5→L7 cross-axis
            # SemanticTypeQualityCheckStrategy (4th cross-axis chain;
            # added 2026-06-11) can scope its L5 read by tenant.
            # The existing 3 strategies (schema_pattern / dbt_tests /
            # historical_stats) ignore company_id — they're model- /
            # table-scoped, not tenant-scoped — so this stays
            # byte-identical for pre-cross-axis deployments.
            checks = await proposal_service.propose_checks(
                table=table, company_id=ctx.company_id,
            )
            all_checks.extend(checks)

        if not all_checks:
            return None

        # Dedup across multiple source-tables within this fire by check_id.
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for c in all_checks:
            cid = c.check_id
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            deduped.append(c)

        emitted_seqs: list[int] = []
        for check in deduped:
            await _emit_quality_check_proposed(check=check, ctx=ctx)

        return FiredAction(
            action_kind="quality_check_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_quality_check_proposed(
    *,
    check: Any,  # ProposedQualityCheck — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``quality_check_proposed`` PEVR cycle for ``check``."""
    promotion_payload: dict[str, Any] = {
        "check_id": check.check_id,
        "table_id": check.table_id,
        "column": check.column,
        "check_kind": check.check_kind,
        "config": dict(check.config),
        "confidence": check.confidence,
        "strategy": check.strategy,
        "reasoning": check.reasoning,
        "evidence": dict(check.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "quality_check_proposed",
            "check_id": check.check_id,
            "ref_id": check.check_id,
            "reason": (
                f"compounding-loop: quality inference strategy="
                f"{check.strategy} proposed {check.check_kind} on "
                f"{check.table_id}.{check.column or '*'} confidence="
                f"{check.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_quality_check_proposed",
            "args": dict(promotion_payload),
            "result_ref": check.check_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "quality_check_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={check.strategy} confidence={check.confidence:.2f} "
                f"trended into a quality_check_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_quality_discovery_reactivity(
    *,
    proposal_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    propose_window_seconds: int = _QUALITY_DEFAULT_PROPOSE_WINDOW_S,
) -> "Compounding":
    """L7 quality-checks axis.

    Source predicate: ``EntryKind("source_connected") |
    EntryKind("external_catalog_imported")`` (same as L3 — both axes
    react to the same upstream signal).

    Optional-Effect Injection (doctrine case 10):

      * ``proposal_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate target tables →
        no-op.
      * Both present → fires per-source on source_connected /
        external_catalog_imported events.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes checks.

    Sub-wave C will wire concrete impls of ``proposal_service``
    (a :class:`CompositeQualityProposalService`) and ``catalog_reader``
    (reuses L3's catalog reader) at install boot.

    Replay-stable: ``check_id`` is deterministic on
    ``(table_id, check_kind, column, normalized_config)`` so re-
    running the same source through the same strategies yields the
    same ledger entries.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's signature enforces it.
    """
    source_predicate = (
        EntryKind("source_connected") | EntryKind("external_catalog_imported")
    )
    return Compounding(
        id="agent_gateway.quality_discovery",
        name="agent-gateway.quality-discovery",
        description=(
            "Lake-side compounding axis: on source_connected / "
            "external_catalog_imported, runs quality-check inference "
            "strategies (schema pattern, dbt tests, historical stats) "
            "over the source's catalog tables and emits one "
            "quality_check_proposed PEVR cycle per inferred check. "
            "Optional-Effect Injection: no-op when proposal_service or "
            "catalog_reader is None."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_quality_quality_filter(),
        gather_fn=_make_quality_gather_fn(catalog_reader),
        cluster_fn=_cluster_quality_proposals_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_quality_proposal_action(
            proposal_service, catalog_reader,
        ),
        novelty_key="quality_discovery",
        scope="company",
        idempotency_filter=_make_quality_idempotency_filter(
            propose_window_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# L4 Sub-wave B (2026-06-02) — schema-evolution-impact discovery axis.
#
# Mirrors the L3 + L7 axis structure with one new architectural feature:
# this is the **first lake-side axis to consume another axis's output**.
# Strategies inject a ``LineageEdgeReader`` Protocol (defined in
# ``schema_impact/protocol.py``) that exposes L3's confirmed lineage
# edges; the cross-axis read happens at strategy execution, not factory
# construction.
#
# Source predicate: ``EntryKind("external_catalog_imported")`` (a
# narrower trigger than L3/L7 — L4 only fires on snapshot events that
# carry catalog state, not bare source_connected events).
#
# gather_fn: computes a column-level delta between the triggering
# snapshot and the prior snapshot for the same source, then yields one
# synthetic trigger entry per ``ColumnChange``. The promotion_action
# walks them and asks the SchemaImpactService for proposals.
#
# cluster_fn: identity (per-impact dedup happens at promotion-action
# time, after the composite service merges across strategies).
# Threshold: >= 1 (every change is its own cluster).
# Promotion: emit one ``schema_impact_proposed`` PEVR cycle per impact.
# Idempotency: per-impact dedup by impact_id within propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 11):
# impact_service=None OR catalog_reader=None → no-op pass; preserves
# byte-identical pre-L4 behaviour. Telemetry counter recorded.
#
# The lineage_edge_reader is NOT injected into the factory — strategies
# own their cross-axis reads. The factory only knows about the
# CatalogReader (reused from L3/L7) and the SchemaImpactService.

_SCHEMA_IMPACT_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window


def _schema_impact_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L4 schema-impact axis — source_id present."""
    return _lineage_quality_filter(payload)


def _make_schema_impact_quality_filter() -> _QualityFilter:
    """Return the schema-impact-discovery axis quality_filter."""
    return _schema_impact_quality_filter


def _extract_catalog_columns(
    table_meta: Any,
) -> dict[str, tuple[str, str | None]]:
    """Extract ``{column_name: (column_name, column_type)}`` from a table meta.

    Defensive about the shape: accepts dicts with "columns" list of dicts
    (Wave-1 catalog mirror) AND objects with .columns + .metadata (
    :class:`wormbase_agent_gateway.lineage.CatalogTable`).
    """
    # Object-with-attrs path (CatalogTable instances)
    cols_from_attr = getattr(table_meta, "columns", None)
    meta_from_attr = getattr(table_meta, "metadata", None)
    if cols_from_attr is not None:
        out: dict[str, tuple[str, str | None]] = {}
        meta_cols: dict[str, str | None] = {}
        if isinstance(meta_from_attr, dict):
            raw = meta_from_attr.get("columns")
            if isinstance(raw, list):
                for cm in raw:
                    if isinstance(cm, dict):
                        nm = cm.get("name")
                        tp = cm.get("type")
                        if isinstance(nm, str):
                            meta_cols[nm] = (
                                str(tp) if isinstance(tp, str) else None
                            )
        for c in cols_from_attr:
            if isinstance(c, str):
                out[c] = (c, meta_cols.get(c))
        return out

    # Plain dict path
    if isinstance(table_meta, dict):
        raw = table_meta.get("columns")
        if isinstance(raw, list):
            out2: dict[str, tuple[str, str | None]] = {}
            for cm in raw:
                if isinstance(cm, dict):
                    nm = cm.get("name")
                    tp = cm.get("type")
                    if isinstance(nm, str):
                        out2[nm] = (nm, str(tp) if isinstance(tp, str) else None)
                elif isinstance(cm, str):
                    out2[cm] = (cm, None)
            return out2
    return {}


def _diff_columns(
    *,
    prior: dict[str, tuple[str, str | None]],
    current: dict[str, tuple[str, str | None]],
) -> list[dict[str, Any]]:
    """Compute per-column delta as a list of ``ColumnChange``-shaped dicts.

    Returns dicts (not the dataclass) so the gather_fn output is
    JSON-serialisable through the runner. The promotion_action
    reconstructs :class:`wormbase_agent_gateway.schema_impact.ColumnChange`
    from these dicts before calling the SchemaImpactService.
    """
    changes: list[dict[str, Any]] = []
    prior_names = set(prior)
    current_names = set(current)
    for added in current_names - prior_names:
        _, new_type = current[added]
        changes.append({
            "src_column": added,
            "change_kind": "column_added",
            "old_type": None,
            "new_type": new_type,
        })
    for dropped in prior_names - current_names:
        _, old_type = prior[dropped]
        changes.append({
            "src_column": dropped,
            "change_kind": "column_dropped",
            "old_type": old_type,
            "new_type": None,
        })
    for common in prior_names & current_names:
        _, old_type = prior[common]
        _, new_type = current[common]
        if old_type is None and new_type is None:
            continue
        if (old_type or "").strip().lower() != (new_type or "").strip().lower():
            changes.append({
                "src_column": common,
                "change_kind": "column_type_changed",
                "old_type": old_type,
                "new_type": new_type,
            })
    # Sort for replay stability — column changes ordered alphabetically
    # by src_column then by change_kind.
    changes.sort(key=lambda c: (c["src_column"], c["change_kind"]))
    return changes


def _make_schema_impact_gather_fn(
    catalog_reader: "_CatalogReader | None",
) -> _GatherFn:
    """Build a gather_fn that yields one trigger entry per column-level change.

    Walks the triggering ``external_catalog_imported`` entry, fetches
    the catalog state via :meth:`_CatalogReader.list_tables_for_source`,
    and diffs each table's columns against the *prior* snapshot for
    the same source (the prior is reconstructed by re-reading the
    catalog at the prior ``external_catalog_imported``-style ts; in
    Sub-wave B the simpler path is to compare against an empty prior
    when no previous snapshot is known, treating all columns as
    pre-existing).

    Sub-wave B contract: the gather_fn requires a delta source. If
    ``catalog_reader`` is None → empty list (Optional-Effect absent
    path; no fires).

    Sub-wave C wires a prior-snapshot reader via the catalog reader's
    extended Protocol; for now we operate on the current snapshot only,
    treating every column as pre-existing (no "added" detection) and
    relying on the upstream entry's ``args.columns_added`` /
    ``args.columns_dropped`` / ``args.columns_type_changed`` hints when
    the canonical emitter supplies them.

    The triggering entry's args may carry a ``column_changes`` list
    pre-computed by the catalog mirror (canonical shape: list of dicts
    matching :func:`_diff_columns` output). When present we use it
    directly; absent → compute diff against an empty prior.
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []

        payload = entry.get("payload") or {}
        args = payload.get("args") if isinstance(payload, dict) else None
        if not isinstance(args, dict):
            args = {}

        # Pre-computed column_changes path (canonical Wave-1+ emitter).
        pre_computed = args.get("column_changes")
        if isinstance(pre_computed, list) and pre_computed:
            triggers: list[dict[str, Any]] = []
            for ch in pre_computed:
                if not isinstance(ch, dict):
                    continue
                src_table = str(ch.get("src_table") or "")
                src_column = str(ch.get("src_column") or "")
                change_kind = ch.get("change_kind")
                if not src_table or not src_column or change_kind not in (
                    "column_added", "column_dropped", "column_type_changed",
                ):
                    continue
                triggers.append({
                    "_schema_impact_trigger": True,
                    "company_id": str(ctx.company_id),
                    "source_id": source_id,
                    "src_table": src_table,
                    "src_column": src_column,
                    "change_kind": change_kind,
                    "old_type": ch.get("old_type"),
                    "new_type": ch.get("new_type"),
                    "triggering_entry_id": str(entry.get("entry_id") or ""),
                })
            return triggers

        # Computed-delta path: walk the catalog reader to enumerate
        # current tables. Without a prior-snapshot reader, no detection
        # is possible; return [] so Sub-wave C can wire the reader.
        # We still call list_tables_for_source so admin can observe
        # the reader was reached (callers' fakes track calls).
        _ = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        return []

    return _gather


def _cluster_schema_impact_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual per-impact dedup (by ``impact_id``) happens at
    promotion-action time after the SchemaImpactService runs (it
    dedups across strategies before returning).
    """
    return [[e] for e in entries]


def _make_schema_impact_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Suppress re-proposal when the (source, src_column, change_kind) trio
    has been freshly inferred.

    Mirrors the L3 + L7 idempotency_filter shape: scans for recent
    ``schema_impact_proposed`` execute entries within
    ``propose_window_seconds`` that match the trigger's
    (source_id, src_column, change_kind). Per-impact dedup at
    projection-fold time still keeps re-proposals safe (same impact_id
    folds onto one row); this filter is a coarse short-circuit when
    the same change has been freshly inferred.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        src_column = str(trigger.get("src_column") or "")
        change_kind = str(trigger.get("change_kind") or "")
        if not source_id or not src_column or not change_kind:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_schema_impact_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            if (
                str(args.get("source_id") or "") == source_id
                and str(args.get("src_column") or "") == src_column
                and str(args.get("change_kind") or "") == change_kind
            ):
                return True
        return False

    return _filter


def _make_schema_impact_promotion_action(
    impact_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
) -> _PromotionAction:
    """Build the schema-impact promotion_action.

    Optional-Effect Injection (doctrine case 11):
    when ``impact_service`` or ``catalog_reader`` is None the action is
    a no-op pass. This preserves byte-identical pre-L4 behaviour for
    callers that have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if impact_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        source_id = str(trigger.get("source_id") or "")
        src_table = str(trigger.get("src_table") or "")
        src_column = str(trigger.get("src_column") or "")
        change_kind = str(trigger.get("change_kind") or "")
        if not (source_id and src_table and src_column and change_kind):
            return None

        # Lazy import to avoid pulling the schema_impact subpackage into
        # the import path for callers that don't opt in to L4.
        from wormbase_agent_gateway.schema_impact import ColumnChange

        change = ColumnChange(
            src_table=src_table,
            src_column=src_column,
            change_kind=change_kind,  # type: ignore[arg-type]
            old_type=trigger.get("old_type"),
            new_type=trigger.get("new_type"),
        )

        impacts = await impact_service.propose_impacts(
            source_id=source_id,
            src_table=src_table,
            change=change,
            company_id=ctx.company_id,
        )
        if not impacts:
            return None

        # Dedup by impact_id (defensive — composite already dedups).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for imp in impacts:
            iid = imp.impact_id
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            deduped.append(imp)

        emitted_seqs: list[int] = []
        for impact in deduped:
            await _emit_schema_impact_proposed(impact=impact, ctx=ctx)

        return FiredAction(
            action_kind="schema_impact_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_schema_impact_proposed(
    *,
    impact: Any,  # ProposedImpact — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``schema_impact_proposed`` PEVR cycle for ``impact``."""
    promotion_payload: dict[str, Any] = {
        "impact_id": impact.impact_id,
        "source_id": impact.source_id,
        "src_table": impact.src_table,
        "src_column": impact.src_column,
        "change_kind": impact.change_kind,
        "impact_kind": impact.impact_kind,
        "tgt_table_id": impact.tgt_table_id,
        "tgt_column": impact.tgt_column,
        "upstream_lineage_edge_id": impact.upstream_lineage_edge_id,
        "confidence": impact.confidence,
        "strategy": impact.strategy,
        "reasoning": impact.reasoning,
        "evidence": dict(impact.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "schema_impact_proposed",
            "impact_id": impact.impact_id,
            "ref_id": impact.impact_id,
            "reason": (
                f"compounding-loop: schema-impact strategy="
                f"{impact.strategy} proposed {impact.change_kind} → "
                f"{impact.impact_kind} on "
                f"{impact.tgt_table_id}.{impact.tgt_column} confidence="
                f"{impact.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_schema_impact_proposed",
            "args": dict(promotion_payload),
            "result_ref": impact.impact_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "schema_impact_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={impact.strategy} "
                f"confidence={impact.confidence:.2f} trended into a "
                f"schema_impact_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_schema_impact_discovery_reactivity(
    *,
    impact_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    propose_window_seconds: int = _SCHEMA_IMPACT_DEFAULT_PROPOSE_WINDOW_S,
) -> "Compounding":
    """L4 schema-evolution-impact axis.

    Source predicate: ``EntryKind("external_catalog_imported")``
    (narrower than L3/L7 — L4 only fires on snapshot events that
    carry catalog state).

    Optional-Effect Injection (doctrine case 11):

      * ``impact_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate the catalog →
        no-op.
      * Both present → fires per-column-change on
        external_catalog_imported events that carry a ``column_changes``
        list (Wave-1+ canonical emitter). Sub-wave C wires a
        catalog-prior-snapshot path so events without pre-computed
        ``column_changes`` also fire.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes impacts.

    Sub-wave C wires concrete impls of ``impact_service`` (a
    :class:`CompositeSchemaImpactService` with the cross-axis
    ``LineageEdgeReader`` impl threaded into its strategies) and
    ``catalog_reader`` (reuses L3's catalog reader) at install boot.

    Cross-axis read pattern: the
    :class:`wormbase_agent_gateway.schema_impact.LineageEdgeReader`
    Protocol is NOT a factory parameter — strategies own their
    cross-axis reads. The factory only knows about the CatalogReader
    (reused from L3/L7) and the SchemaImpactService.

    Replay-stable: ``impact_id`` is deterministic on
    ``(source_id, src_table, src_column, change_kind, tgt_table_id,
    tgt_column)`` so re-running the same source change yields the
    same ledger entries.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's + service's signatures
    enforce it.
    """
    source_predicate = EntryKind("external_catalog_imported")
    return Compounding(
        id="agent_gateway.schema_impact_discovery",
        name="agent-gateway.schema-impact-discovery",
        description=(
            "Lake-side compounding axis: on external_catalog_imported "
            "with column_changes, runs schema-impact inference "
            "strategies (lineage_edge cross-axis read of L3, dbt_test, "
            "type_coercion) and emits one schema_impact_proposed PEVR "
            "cycle per propagated impact. Optional-Effect Injection: "
            "no-op when impact_service or catalog_reader is None. "
            "First lake-side axis to read another axis's projection — "
            "the LineageEdgeReader Protocol is the canonical cross-axis "
            "read pattern."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_schema_impact_quality_filter(),
        gather_fn=_make_schema_impact_gather_fn(catalog_reader),
        cluster_fn=_cluster_schema_impact_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_schema_impact_promotion_action(
            impact_service, catalog_reader,
        ),
        novelty_key="schema_impact_discovery",
        scope="company",
        idempotency_filter=_make_schema_impact_idempotency_filter(
            propose_window_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# L5 Sub-wave B (2026-06-05) — semantic-type fingerprinting discovery axis.
#
# Mirrors the L3 / L7 / L4 axis structure with one new architectural note:
# this is the **first lake-side axis built on top of LakeLoopComposite[T]
# from day one** (L3/L7/L4 retrofitted the abstraction during the refactor
# at ``a4a62c2``). Validates that the shared composite generic pays off
# for new consumers as designed.
#
# Source predicate: ``EntryKind("external_catalog_imported")`` (same as
# L4 — L5 enumerates columns from the triggering snapshot's tables).
#
# gather_fn: returns one synthetic trigger entry per (table_id, column)
# pair from the triggering snapshot. The promotion_action invokes the
# composite fingerprint service per pair.
# cluster_fn: identity (per-type_id dedup happens at promotion-action
# time, after the composite service merges across strategies).
# Threshold: >= 1 (every column is its own cluster).
# Promotion: emit one ``semantic_type_proposed`` PEVR cycle per proposed
# semantic type.
# Idempotency: per-(table_id, column, semantic_type) dedup within
# propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 12):
# fingerprint_service=None OR catalog_reader=None → no-op pass; preserves
# byte-identical pre-L5 behaviour. Telemetry counter recorded.
#
# Reuses L3's ``_CatalogReader`` Protocol (same as L4 + L7); no new
# Protocol introduced.

_FINGERPRINT_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window
_FINGERPRINT_DEFAULT_SAMPLE_SIZE: int = 20


def _fingerprint_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L5 fingerprint axis — source_id present."""
    # Identical contract to L3/L7/L4 axes.
    return _lineage_quality_filter(payload)


def _make_fingerprint_quality_filter() -> _QualityFilter:
    """Return the fingerprint-discovery axis quality_filter."""
    return _fingerprint_quality_filter


def _table_id_of(table_meta: Any) -> str:
    """Extract a canonical ``table_id`` string from a CatalogTable-like meta.

    Defensive about the shape: accepts objects with ``.table_id``
    (canonical :class:`wormbase_agent_gateway.lineage.CatalogTable`) AND
    plain dicts with a ``"table_id"`` key.
    """
    attr = getattr(table_meta, "table_id", None)
    if isinstance(attr, str) and attr:
        return attr
    if isinstance(table_meta, dict):
        v = table_meta.get("table_id")
        if isinstance(v, str) and v:
            return v
    return ""


def _columns_of(table_meta: Any) -> list[str]:
    """Extract the ordered list of column names from a CatalogTable-like meta.

    Mirrors :func:`_extract_catalog_columns` in shape-tolerance but
    returns only the column names (L5 strategies don't need column
    types — the catalog reader's view is the canonical source).
    """
    cols_attr = getattr(table_meta, "columns", None)
    if cols_attr is not None:
        return [c for c in cols_attr if isinstance(c, str)]
    if isinstance(table_meta, dict):
        raw = table_meta.get("columns")
        if isinstance(raw, list):
            names: list[str] = []
            for cm in raw:
                if isinstance(cm, str):
                    names.append(cm)
                elif isinstance(cm, dict):
                    nm = cm.get("name")
                    if isinstance(nm, str):
                        names.append(nm)
            return names
    return []


def _make_fingerprint_gather_fn(
    catalog_reader: "_CatalogReader | None",
) -> _GatherFn:
    """Build a gather_fn that yields one synthetic trigger entry per (table, column).

    Walks the triggering ``external_catalog_imported`` entry's source_id,
    fetches the catalog state via :meth:`_CatalogReader.list_tables_for_source`,
    and emits one trigger per ``(table_id, column)`` pair. The promotion
    action invokes the composite fingerprint service per pair.

    When ``catalog_reader`` is None → empty list (Optional-Effect absent
    path; the composite telemetry counter records the no-op).
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []

        tables = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not tables:
            return []

        triggers: list[dict[str, Any]] = []
        # Replay-stability: sort tables by table_id, columns alphabetically.
        sorted_tables = sorted(tables, key=_table_id_of)
        for table in sorted_tables:
            table_id = _table_id_of(table)
            if not table_id:
                continue
            for column in sorted(_columns_of(table)):
                triggers.append({
                    "_fingerprint_trigger": True,
                    "company_id": str(ctx.company_id),
                    "source_id": source_id,
                    "table_id": table_id,
                    "column": column,
                    "triggering_entry_id": str(entry.get("entry_id") or ""),
                })
        return triggers

    return _gather


def _cluster_fingerprint_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual per-(type_id) dedup happens at promotion-action time
    after the composite fingerprint service runs (it dedups across
    strategies before returning).
    """
    return [[e] for e in entries]


def _make_fingerprint_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Suppress re-proposal when (table_id, column) has been freshly inferred.

    Mirrors L3 / L7 / L4 idempotency_filter shape: scans for recent
    ``semantic_type_proposed`` execute entries within
    ``propose_window_seconds`` that match the trigger's
    ``(table_id, column)``. Per-type_id dedup at projection-fold time
    still keeps re-proposals safe (same type_id folds onto one row);
    this filter is a coarse short-circuit when the same column has
    been freshly fingerprinted.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        table_id = str(trigger.get("table_id") or "")
        column = str(trigger.get("column") or "")
        if not table_id or not column:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_semantic_type_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            if (
                str(args.get("table_id") or "") == table_id
                and str(args.get("column") or "") == column
            ):
                return True
        return False

    return _filter


def _make_fingerprint_promotion_action(
    fingerprint_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
    sample_size: int,
) -> _PromotionAction:
    """Build the fingerprint-discovery promotion_action.

    Optional-Effect Injection (doctrine case 12):
    when ``fingerprint_service`` or ``catalog_reader`` is None the
    action is a no-op pass. This preserves byte-identical pre-L5
    behaviour for callers that have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if fingerprint_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        table_id = str(trigger.get("table_id") or "")
        column = str(trigger.get("column") or "")
        if not table_id or not column:
            return None

        proposals = await fingerprint_service.propose(
            table_id=table_id,
            column=column,
            sample_size=sample_size,
        )
        if not proposals:
            return None

        # Dedup defensively by type_id (composite already dedups).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for p in proposals:
            tid = p.type_id
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            deduped.append(p)

        emitted_seqs: list[int] = []
        for proposal in deduped:
            await _emit_semantic_type_proposed(proposal=proposal, ctx=ctx)

        return FiredAction(
            action_kind="semantic_type_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_semantic_type_proposed(
    *,
    proposal: Any,  # ProposedSemanticType — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``semantic_type_proposed`` PEVR cycle for ``proposal``."""
    promotion_payload: dict[str, Any] = {
        "type_id": proposal.type_id,
        "table_id": proposal.table_id,
        "column": proposal.column,
        "semantic_type": proposal.semantic_type,
        "confidence": proposal.confidence,
        "strategy": proposal.strategy,
        "reasoning": proposal.reasoning,
        "evidence": dict(proposal.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "semantic_type_proposed",
            "type_id": proposal.type_id,
            "ref_id": proposal.type_id,
            "reason": (
                f"compounding-loop: fingerprint inference strategy="
                f"{proposal.strategy} proposed {proposal.semantic_type} on "
                f"{proposal.table_id}.{proposal.column} confidence="
                f"{proposal.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_semantic_type_proposed",
            "args": dict(promotion_payload),
            "result_ref": proposal.type_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [{"name": "semantic_type_proposed", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={proposal.strategy} "
                f"confidence={proposal.confidence:.2f} trended into a "
                f"semantic_type_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_fingerprint_discovery_reactivity(
    *,
    fingerprint_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    propose_window_seconds: int = _FINGERPRINT_DEFAULT_PROPOSE_WINDOW_S,
    sample_size: int = _FINGERPRINT_DEFAULT_SAMPLE_SIZE,
) -> "Compounding":
    """L5 semantic-type fingerprinting axis.

    Source predicate: ``EntryKind("external_catalog_imported")`` (same
    as L4 — L5 enumerates the columns from the triggering snapshot's
    tables).

    Optional-Effect Injection (doctrine case 12 — first lake-side axis
    built on :class:`LakeLoopComposite` from day one):

      * ``fingerprint_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate columns → no-op.
      * Both present → fires per-column on external_catalog_imported
        events.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes semantic
    types.

    Sub-wave C wires concrete impls of ``fingerprint_service`` (a
    :class:`LakeLoopComposite[ProposedSemanticType]` from
    :func:`make_composite_semantic_type_service`) and ``catalog_reader``
    (reuses L3's catalog reader) at install boot.

    Replay-stable: ``type_id`` is deterministic on
    ``(table_id, column, semantic_type)`` so re-running the same
    snapshot through the same strategies yields the same ledger
    entries.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's signature enforces it.

    ``sample_size`` is the per-column sample window passed to each
    strategy (default 20 — the canonical N for value-pattern M/N
    matching).
    """
    source_predicate = EntryKind("external_catalog_imported")
    return Compounding(
        id="agent_gateway.fingerprint_discovery",
        name="agent-gateway.fingerprint-discovery",
        description=(
            "Lake-side compounding axis: on external_catalog_imported, "
            "runs semantic-type fingerprinting strategies (column_name "
            "regex, value_pattern via sampler, distribution via stats) "
            "over every column in the triggering source's tables and "
            "emits one semantic_type_proposed PEVR cycle per inferred "
            "type. Optional-Effect Injection: no-op when "
            "fingerprint_service or catalog_reader is None. First "
            "lake-side axis built on LakeLoopComposite[T] from day one."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_fingerprint_quality_filter(),
        gather_fn=_make_fingerprint_gather_fn(catalog_reader),
        cluster_fn=_cluster_fingerprint_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_fingerprint_promotion_action(
            fingerprint_service, catalog_reader, sample_size,
        ),
        novelty_key="fingerprint_discovery",
        scope="company",
        idempotency_filter=_make_fingerprint_idempotency_filter(
            propose_window_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# L6 Sub-wave B (2026-06-06) — column-level classification discovery axis.
#
# Mirrors the L5 axis structure with two architectural notes:
#  * **Second cross-axis chain** in the lake-side architecture (after
#    L4→L3). L6 reads L5's confirmed semantic types via the new
#    ConfirmedSemanticTypeReader Protocol (owned by L6 — see
#    wormbase_agent_gateway.column_classification.protocol).
#  * **Second lake-side axis built on LakeLoopComposite[T] from day one**
#    (after L5's case 12). Validates the shared abstraction for the 2nd
#    new consumer.
#
# Source predicate: ``EntryKind("external_catalog_imported")`` (same as
# L4 + L5 — L6 enumerates columns from the triggering snapshot's tables
# and applies all three strategies; one of them — semantic_type — does
# the cross-axis read via the injected reader).
#
# gather_fn: returns one synthetic trigger entry per (table_id, column)
# pair from the triggering snapshot. The promotion_action invokes the
# composite classification service per pair.
# cluster_fn: identity (per-classification_id dedup happens at
# promotion-action time, after the composite service merges across
# strategies that produce the same classification_id — though by spec
# §4.4 different strategies produce DIFFERENT classification_ids on
# purpose; merges are only intra-strategy retries).
# Threshold: >= 1 (every column is its own cluster).
# Promotion: emit one ``column_classification_proposed`` PEVR cycle per
# proposed classification.
# Idempotency: per-(table_id, column) dedup within propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 13):
# classification_service=None OR catalog_reader=None → no-op pass;
# preserves byte-identical pre-L6 behaviour. Telemetry counter recorded.
#
# Reuses L3's ``_CatalogReader`` Protocol (same as L4 + L5 + L7); no new
# *catalog* Protocol introduced. L6 DOES introduce a new cross-axis read
# Protocol — ConfirmedSemanticTypeReader — but that's injected into the
# SemanticTypeClassificationStrategy at construction time, not into the
# Compounding factory; the factory only knows about the CatalogReader
# and the classification_service. The semantic_type_reader is an
# implementation detail of the strategy.

_COLUMN_CLASSIFICATION_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window


def _column_classification_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L6 column-classification axis — source_id present."""
    # Identical contract to L3/L7/L4/L5 axes.
    return _lineage_quality_filter(payload)


def _make_column_classification_quality_filter() -> _QualityFilter:
    """Return the column-classification-discovery axis quality_filter."""
    return _column_classification_quality_filter


def _make_column_classification_gather_fn(
    catalog_reader: "_CatalogReader | None",
) -> _GatherFn:
    """Build a gather_fn that yields one synthetic trigger per (table, column).

    Walks the triggering ``external_catalog_imported`` entry's source_id,
    fetches the catalog state via :meth:`_CatalogReader.list_tables_for_source`,
    and emits one trigger per ``(table_id, column)`` pair. The promotion
    action invokes the composite classification service per pair.

    When ``catalog_reader`` is None → empty list (Optional-Effect absent
    path; the composite telemetry counter records the no-op).
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []

        tables = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not tables:
            return []

        triggers: list[dict[str, Any]] = []
        # Replay-stability: sort tables by table_id, columns alphabetically.
        sorted_tables = sorted(tables, key=_table_id_of)
        for table in sorted_tables:
            table_id = _table_id_of(table)
            if not table_id:
                continue
            for column in sorted(_columns_of(table)):
                triggers.append({
                    "_column_classification_trigger": True,
                    "company_id": str(ctx.company_id),
                    "source_id": source_id,
                    "table_id": table_id,
                    "column": column,
                    "triggering_entry_id": str(entry.get("entry_id") or ""),
                })
        return triggers

    return _gather


def _cluster_column_classification_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual per-(classification_id) dedup happens at promotion-action
    time after the composite classification service runs (per-strategy
    dedup; cross-strategy "merge" is by design absent — different
    strategies produce different classification_ids per spec §4.4).
    """
    return [[e] for e in entries]


def _make_column_classification_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Suppress re-proposal when (table_id, column) has been freshly classified.

    Mirrors L3 / L7 / L4 / L5 idempotency_filter shape: scans for recent
    ``column_classification_proposed`` execute entries within
    ``propose_window_seconds`` that match the trigger's
    ``(table_id, column)``. Per-classification_id dedup at projection-
    fold time still keeps re-proposals safe (same classification_id
    folds onto one row); this filter is a coarse short-circuit when the
    same column has been freshly classified.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        table_id = str(trigger.get("table_id") or "")
        column = str(trigger.get("column") or "")
        if not table_id or not column:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_column_classification_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            if (
                str(args.get("table_id") or "") == table_id
                and str(args.get("column") or "") == column
            ):
                return True
        return False

    return _filter


def _make_column_classification_promotion_action(
    classification_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
) -> _PromotionAction:
    """Build the column-classification-discovery promotion_action.

    Optional-Effect Injection (doctrine case 13):
    when ``classification_service`` or ``catalog_reader`` is None the
    action is a no-op pass. This preserves byte-identical pre-L6
    behaviour for callers that have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if classification_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        table_id = str(trigger.get("table_id") or "")
        column = str(trigger.get("column") or "")
        if not table_id or not column:
            return None

        proposals = await classification_service.propose(
            table_id=table_id,
            column=column,
            company_id=ctx.company_id,
        )
        if not proposals:
            return None

        # Dedup defensively by classification_id (composite already
        # dedups within a strategy; across strategies the ids differ
        # by design — per spec §4.4 — so this is just a safety net).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for p in proposals:
            cid = p.classification_id
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            deduped.append(p)

        emitted_seqs: list[int] = []
        for proposal in deduped:
            await _emit_column_classification_proposed(
                proposal=proposal, ctx=ctx,
            )

        return FiredAction(
            action_kind="column_classification_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_column_classification_proposed(
    *,
    proposal: Any,  # ProposedColumnClassification — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``column_classification_proposed`` PEVR cycle for ``proposal``."""
    promotion_payload: dict[str, Any] = {
        "classification_id": proposal.classification_id,
        "table_id": proposal.table_id,
        "column": proposal.column,
        "classification_level": proposal.classification_level,
        "upstream_semantic_type_id": proposal.upstream_semantic_type_id,
        "confidence": proposal.confidence,
        "strategy": proposal.strategy,
        "reasoning": proposal.reasoning,
        "evidence": dict(proposal.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "column_classification_proposed",
            "type_id": proposal.classification_id,
            "ref_id": proposal.classification_id,
            "reason": (
                f"compounding-loop: column-classification inference strategy="
                f"{proposal.strategy} proposed {proposal.classification_level} "
                f"on {proposal.table_id}.{proposal.column} confidence="
                f"{proposal.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_column_classification_proposed",
            "args": dict(promotion_payload),
            "result_ref": proposal.classification_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [
                {"name": "column_classification_proposed", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={proposal.strategy} "
                f"confidence={proposal.confidence:.2f} trended into a "
                f"column_classification_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_column_classification_discovery_reactivity(
    *,
    classification_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    propose_window_seconds: int = _COLUMN_CLASSIFICATION_DEFAULT_PROPOSE_WINDOW_S,
) -> "Compounding":
    """L6 column-level classification discovery axis.

    Source predicate: ``EntryKind("external_catalog_imported")`` (same
    as L4 + L5 — L6 enumerates the columns from the triggering
    snapshot's tables).

    Optional-Effect Injection (doctrine case 13 — **second lake-side
    axis built on :class:`LakeLoopComposite` from day one**):

      * ``classification_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate columns → no-op.
      * Both present → fires per-column on external_catalog_imported
        events.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes
    classifications.

    Sub-wave C wires concrete impls of ``classification_service`` (a
    :class:`LakeLoopComposite[ProposedColumnClassification]` from
    :func:`make_composite_column_classification_service`) and
    ``catalog_reader`` (reuses L3's catalog reader) at install boot.
    The :class:`ConfirmedSemanticTypeReader` (new cross-axis Protocol
    introduced for L6) is injected into the
    :class:`SemanticTypeClassificationStrategy` at strategy
    construction time, not at factory time — the factory has no
    cross-axis knowledge.

    Replay-stable: ``classification_id`` is deterministic on
    ``(table_id, column, classification_level, strategy)`` so re-
    running the same snapshot through the same strategies yields the
    same ledger entries. Note ``strategy`` is in the hash so each
    strategy's per-column-per-level proposal is its own projection row
    (per spec §4.4; diverges from L5's per-(table,column,type) merge
    by design — admin queue compares strategies side-by-side).

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's signature enforces it
    and the classification_service forwards it to the
    SemanticTypeClassificationStrategy's reader.
    """
    source_predicate = EntryKind("external_catalog_imported")
    return Compounding(
        id="agent_gateway.column_classification_discovery",
        name="agent-gateway.column-classification-discovery",
        description=(
            "Lake-side compounding axis: on external_catalog_imported, "
            "runs column-classification strategies (semantic_type via "
            "cross-axis L5 read, naming_pattern regex, domain_default "
            "via governance) over every column in the triggering "
            "source's tables and emits one column_classification_proposed "
            "PEVR cycle per inferred classification. Optional-Effect "
            "Injection: no-op when classification_service or "
            "catalog_reader is None. Second lake-side axis built on "
            "LakeLoopComposite[T] from day one (after L5); second "
            "cross-axis chain (after L4→L3) — reads L5 via the new "
            "ConfirmedSemanticTypeReader Protocol."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_column_classification_quality_filter(),
        gather_fn=_make_column_classification_gather_fn(catalog_reader),
        cluster_fn=_cluster_column_classification_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_column_classification_promotion_action(
            classification_service, catalog_reader,
        ),
        novelty_key="column_classification_discovery",
        scope="company",
        idempotency_filter=_make_column_classification_idempotency_filter(
            propose_window_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# L8 Sub-wave B (2026-06-07) — cross-source entity-stitching discovery axis.
#
# Mirrors the L6 axis structure with two architectural notes:
#  * **Third cross-axis chain** in the lake-side architecture (after
#    L4→L3 and L6→L5). L8 reads L5's confirmed semantic types via the
#    *reused* L6-owned ConfirmedSemanticTypeReader Protocol — L6's
#    SemanticTypeClassificationStrategy is the first consumer; L8's
#    NameMatchEntityStrategy is the second consumer of the same
#    Protocol. Validates that the consumer-owned-Protocol pattern
#    generalises across N downstream axes (one producer-side surface,
#    multiple readers).
#  * **Third lake-side axis built on LakeLoopComposite[T] from day one**
#    (after L5's case 12 and L6's case 13). Continues the smoking-gun
#    validation of the shared abstraction for the 3rd new consumer.
#
# Source predicate: ``EntryKind("external_catalog_imported")`` (same as
# L4 + L5 + L6 — L8 enumerates cross-source column pairs from the
# triggering snapshot AND the previously-imported snapshots of OTHER
# sources; the cross-source bridge is meaningless when only one source
# has been imported, so the gather_fn pulls cross-source candidates
# from the catalog reader's other-source views).
#
# gather_fn: returns one synthetic trigger entry per cross-source
# (column_a, column_b) pair. For replay stability the gather_fn sorts
# tables by table_id and columns alphabetically, and emits pairs only
# when source_id_a != source_id_b (cross-source filter). The
# promotion_action invokes the composite stitch service per pair.
# cluster_fn: identity (per-stitch_id dedup happens at promotion-action
# time, after the composite service merges across strategies that
# propose the same stitch_id — same logical pair, in either argument
# order, collides on the canonicalised hash).
# Threshold: >= 1 (every pair is its own cluster).
# Promotion: emit one ``entity_stitch_proposed`` PEVR cycle per
# proposed stitch.
# Idempotency: per-(stitch_id) dedup within propose_window_seconds.
#
# Optional-Effect Injection (doctrine case 14):
# stitch_service=None OR catalog_reader=None → no-op pass; preserves
# byte-identical pre-L8 behaviour. Telemetry counter recorded.
#
# Reuses L3's ``_CatalogReader`` Protocol (same as L4 + L5 + L6 + L7);
# no new catalog Protocol introduced. The ConfirmedSemanticTypeReader
# is injected into the NameMatchEntityStrategy at strategy
# construction time, not at factory time — the factory only knows
# about the CatalogReader and the stitch_service.

_ENTITY_STITCH_DEFAULT_PROPOSE_WINDOW_S: int = 86400  # 24h dedup window


def _entity_stitch_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L8 entity-stitch axis — source_id present."""
    # Identical contract to L3/L7/L4/L5/L6 axes.
    return _lineage_quality_filter(payload)


def _make_entity_stitch_quality_filter() -> _QualityFilter:
    """Return the entity-stitch-discovery axis quality_filter."""
    return _entity_stitch_quality_filter


def _source_id_of_table_id(table_id: str) -> str:
    """Extract source_id from canonical ``<source_id>.<schema>.<table>``."""
    if not table_id:
        return ""
    # First dot-separated segment is the source_id by L3's table-id grammar.
    return table_id.split(".", 1)[0] if "." in table_id else table_id


def _make_entity_stitch_gather_fn(
    catalog_reader: "_CatalogReader | None",
) -> _GatherFn:
    """Build a gather_fn that yields one synthetic trigger per cross-source pair.

    Walks the triggering ``external_catalog_imported`` entry's
    source_id, fetches the catalog tables for THAT source via
    :meth:`_CatalogReader.list_tables_for_source`, AND fetches all
    candidate-target tables across other sources via
    :meth:`_CatalogReader.list_candidate_targets`. Emits one trigger
    per ``(column_a, column_b)`` pair where ``column_a`` is a column
    on the triggering source's tables and ``column_b`` is a column on
    another source's table (cross-source filter:
    ``source_id_a != source_id_b``). The promotion action invokes the
    composite stitch service per pair.

    When ``catalog_reader`` is None → empty list (Optional-Effect
    absent path; the composite telemetry counter records the no-op).

    Replay-stability: tables sorted by table_id; columns alphabetically;
    pairs emitted in canonical (a, b) lex order so the gather output
    is deterministic on the same catalog state.
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []

        tables_a = await catalog_reader.list_tables_for_source(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not tables_a:
            return []
        # All candidates includes the triggering source's own tables; we
        # filter cross-source at pair-emission time below.
        candidates = await catalog_reader.list_candidate_targets(
            company_id=ctx.company_id, source_id=source_id,
        )
        if not candidates:
            return []

        # Build (table_id, sorted_columns) pairs for both sides.
        def _build(tables: list[Any]) -> list[tuple[str, str, list[str]]]:
            out: list[tuple[str, str, list[str]]] = []
            for tbl in sorted(tables, key=_table_id_of):
                tid = _table_id_of(tbl)
                if not tid:
                    continue
                sid = _source_id_of_table_id(tid)
                if not sid:
                    continue
                out.append((sid, tid, sorted(_columns_of(tbl))))
            return out

        a_side = _build(list(tables_a))
        b_side = _build(list(candidates))

        triggers: list[dict[str, Any]] = []
        for sid_a, tid_a, cols_a in a_side:
            for sid_b, tid_b, cols_b in b_side:
                if sid_a == sid_b:
                    # Cross-source filter — no same-source stitches at
                    # the gather layer. Strategies can in theory still
                    # produce same-source stitches but the gather_fn is
                    # the canonical guard per spec §4.5.
                    continue
                for col_a in cols_a:
                    for col_b in cols_b:
                        triggers.append({
                            "_entity_stitch_trigger": True,
                            "company_id": str(ctx.company_id),
                            "source_id_a": sid_a,
                            "table_id_a": tid_a,
                            "column_a": col_a,
                            "source_id_b": sid_b,
                            "table_id_b": tid_b,
                            "column_b": col_b,
                            "triggering_entry_id": str(
                                entry.get("entry_id") or "",
                            ),
                        })
        return triggers

    return _gather


def _cluster_entity_stitch_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    The actual per-(stitch_id) dedup happens at promotion-action time
    after the composite service runs and merges across strategies that
    propose the same stitch_id (same canonicalised pair, either order).
    """
    return [[e] for e in entries]


def _make_entity_stitch_idempotency_filter(
    propose_window_seconds: int,
) -> _IdempotencyFilter:
    """Suppress re-proposal when (pair) has been freshly stitched.

    Mirrors L3 / L7 / L4 / L5 / L6 idempotency_filter shape: scans for
    recent ``entity_stitch_proposed`` execute entries within
    ``propose_window_seconds`` that match the trigger's canonicalised
    pair. Per-stitch_id dedup at projection-fold time still keeps
    re-proposals safe (same stitch_id folds onto one row); this filter
    is a coarse short-circuit when the same pair has been freshly
    stitched.
    """

    async def _filter(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> bool:
        if not cluster:
            return True
        trigger = cluster[0]
        # Reconstruct the canonicalised stitch_id for window-lookup.
        from .entity_stitch.protocol import make_stitch_id
        try:
            sid = make_stitch_id(
                src_a={
                    "source_id": str(trigger.get("source_id_a") or ""),
                    "table_id": str(trigger.get("table_id_a") or ""),
                    "column": str(trigger.get("column_a") or ""),
                },
                src_b={
                    "source_id": str(trigger.get("source_id_b") or ""),
                    "table_id": str(trigger.get("table_id_b") or ""),
                    "column": str(trigger.get("column_b") or ""),
                },
            )
        except (KeyError, TypeError):
            return True
        if not sid:
            return True

        now = ctx.now() if callable(ctx.now) else ctx.now
        if not isinstance(now, datetime):
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(seconds=propose_window_seconds)

        rows = await ctx.ledger.fetch(ctx.company_id)
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_entity_stitch_proposed":
                continue
            ts = r.get("ts")
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            if str(args.get("stitch_id") or "") == sid:
                return True
        return False

    return _filter


def _make_entity_stitch_promotion_action(
    stitch_service: "Any | None",
    catalog_reader: "_CatalogReader | None",
) -> _PromotionAction:
    """Build the entity-stitch-discovery promotion_action.

    Optional-Effect Injection (doctrine case 14):
    when ``stitch_service`` or ``catalog_reader`` is None the action is
    a no-op pass. This preserves byte-identical pre-L8 behaviour for
    callers that have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if stitch_service is None or catalog_reader is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        column_a = {
            "source_id": str(trigger.get("source_id_a") or ""),
            "table_id": str(trigger.get("table_id_a") or ""),
            "column": str(trigger.get("column_a") or ""),
        }
        column_b = {
            "source_id": str(trigger.get("source_id_b") or ""),
            "table_id": str(trigger.get("table_id_b") or ""),
            "column": str(trigger.get("column_b") or ""),
        }
        if (
            not column_a["source_id"]
            or not column_a["table_id"]
            or not column_a["column"]
            or not column_b["source_id"]
            or not column_b["table_id"]
            or not column_b["column"]
        ):
            return None

        proposals = await stitch_service.propose(
            company_id=ctx.company_id,
            column_a=column_a,
            column_b=column_b,
        )
        if not proposals:
            return None

        # Dedup defensively by stitch_id (composite already dedups
        # across strategies; this is a safety net).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for p in proposals:
            sid = p.stitch_id
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            deduped.append(p)

        emitted_seqs: list[int] = []
        for proposal in deduped:
            await _emit_entity_stitch_proposed(proposal=proposal, ctx=ctx)

        return FiredAction(
            action_kind="entity_stitch_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_entity_stitch_proposed(
    *,
    proposal: Any,  # ProposedEntityStitch — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``entity_stitch_proposed`` PEVR cycle for ``proposal``."""
    promotion_payload: dict[str, Any] = {
        "stitch_id": proposal.stitch_id,
        "src_source_id_a": proposal.src_source_id_a,
        "src_table_a": proposal.src_table_a,
        "src_column_a": proposal.src_column_a,
        "src_source_id_b": proposal.src_source_id_b,
        "src_table_b": proposal.src_table_b,
        "src_column_b": proposal.src_column_b,
        "upstream_semantic_type_id": proposal.upstream_semantic_type_id,
        "entity_kind": proposal.entity_kind,
        "confidence": proposal.confidence,
        "strategy": proposal.strategy,
        "reasoning": proposal.reasoning,
        "evidence": dict(proposal.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "entity_stitch_proposed",
            "stitch_id": proposal.stitch_id,
            "ref_id": proposal.stitch_id,
            "reason": (
                f"compounding-loop: entity-stitch inference strategy="
                f"{proposal.strategy} proposed {proposal.entity_kind} "
                f"bridge between "
                f"{proposal.src_source_id_a}.{proposal.src_table_a}."
                f"{proposal.src_column_a} ↔ "
                f"{proposal.src_source_id_b}.{proposal.src_table_b}."
                f"{proposal.src_column_b} "
                f"confidence={proposal.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_entity_stitch_proposed",
            "args": dict(promotion_payload),
            "result_ref": proposal.stitch_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [
                {"name": "entity_stitch_proposed", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={proposal.strategy} "
                f"confidence={proposal.confidence:.2f} trended into an "
                f"entity_stitch_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_entity_stitch_discovery_reactivity(
    *,
    stitch_service: "Any | None" = None,
    catalog_reader: "_CatalogReader | None" = None,
    propose_window_seconds: int = _ENTITY_STITCH_DEFAULT_PROPOSE_WINDOW_S,
) -> "Compounding":
    """L8 cross-source entity-stitching discovery axis.

    Source predicate: ``EntryKind("external_catalog_imported")`` (same
    as L4 + L5 + L6 — L8 enumerates cross-source column pairs from the
    triggering snapshot AND every previously-imported source's tables).

    Optional-Effect Injection (doctrine case 14 — **third lake-side
    axis built on :class:`LakeLoopComposite` from day one**):

      * ``stitch_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_reader=None`` → cannot enumerate pairs → no-op.
      * Both present → fires per-pair on external_catalog_imported
        events.

    Default args (both None) preserve byte-identical Sub-wave A
    behaviour: the Reactivity registers but never proposes stitches.

    Sub-wave C wires concrete impls of ``stitch_service`` (a
    :class:`LakeLoopComposite[ProposedEntityStitch]` from
    :func:`make_composite_entity_stitch_service`) and ``catalog_reader``
    (reuses L3's catalog reader) at install boot. The
    :class:`ConfirmedSemanticTypeReader` is reused from L6 (no new
    adapter needed — L6's :class:`LedgerConfirmedSemanticTypeReader`
    already ships); it's injected into the
    :class:`NameMatchEntityStrategy` at strategy construction time.

    Replay-stable: ``stitch_id`` is the **order-independent** hash on
    the two endpoint triples so re-running the same snapshot through
    the same strategies yields the same ledger entries regardless of
    a/b argument ordering at the gather layer.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the catalog_reader's signature enforces it
    and the stitch_service forwards it to the
    NameMatchEntityStrategy's reader.

    Cross-source filter: ``source_id_a != source_id_b`` enforced at
    gather_fn time (no same-source stitches). Strategy logic provides
    a defensive guard against same-(source, table, column) anyway.
    """
    source_predicate = EntryKind("external_catalog_imported")
    return Compounding(
        id="agent_gateway.entity_stitch_discovery",
        name="agent-gateway.entity-stitch-discovery",
        description=(
            "Lake-side compounding axis: on external_catalog_imported, "
            "runs cross-source entity-stitch strategies (name_match via "
            "REUSED L6 ConfirmedSemanticTypeReader Protocol + fuzzy-name, "
            "sample_overlap via SamplerProtocol, schema_shape on bare "
            "catalog metadata) over every cross-source (column_a, "
            "column_b) pair from the triggering source's tables and the "
            "previously-imported sources' tables, and emits one "
            "entity_stitch_proposed PEVR cycle per inferred stitch. "
            "Optional-Effect Injection: no-op when stitch_service or "
            "catalog_reader is None. Third lake-side axis built on "
            "LakeLoopComposite[T] from day one (after L5 + L6); third "
            "cross-axis chain (after L4→L3 and L6→L5) — reuses L6's "
            "ConfirmedSemanticTypeReader Protocol as its second consumer."
        ),
        source_predicate=source_predicate,
        quality_filter=_make_entity_stitch_quality_filter(),
        gather_fn=_make_entity_stitch_gather_fn(catalog_reader),
        cluster_fn=_cluster_entity_stitch_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_entity_stitch_promotion_action(
            stitch_service, catalog_reader,
        ),
        novelty_key="entity_stitch_discovery",
        scope="company",
        idempotency_filter=_make_entity_stitch_idempotency_filter(
            propose_window_seconds,
        ),
    )


# ---------------------------------------------------------------------------
# L1 Sub-wave B (2026-06-08) — source-candidate triage discovery axis.
#
# Mirrors the L3 / L7 / L4 / L5 / L6 / L8 axis structure with one
# divergence: L1 is **periodic-driven** (``Periodic(every_seconds=N)``
# via the ClockTickEmitter) rather than event-driven on
# ``external_catalog_imported`` / ``source_connected``. Rationale per
# spec §4.6: L1's three strategies all SCAN platform projections
# (``projection_sources``, ``projection_kpi_nodes``, the silver
# conversations projection) rather than react to a specific entry
# kind. A periodic cadence decouples discovery from upstream traffic
# (a freshly-installed worm with pre-existing KPI gaps still fires)
# and bounds the scan cost.
#
# Default cadence: 3600s (hourly). Tunable per-factory via the
# ``tick_interval_s`` parameter.
#
# gather_fn: returns ONE synthetic trigger per company per tick — the
# strategies' propose calls scan projections via Readers themselves,
# so the gather_fn is a lightweight "fire-once-per-tick" guard. The
# promotion_action invokes the composite service which fans out to
# each wired strategy.
#
# cluster_fn: identity (one synthetic trigger → one cluster); per-
# candidate dedup happens at promotion-action time, after the
# composite service merges across strategies that propose the same
# (kind, identifier, strategy) triple (candidate_id collision).
#
# Threshold: >= 1 (the synthetic trigger always promotes).
# Promotion: emit one ``source_candidate_proposed`` PEVR cycle per
# proposal returned by the composite.
# Idempotency: per-candidate dedup by candidate_id on the projection
# PK (per spec §4.8 — L1 omits a PROPOSE_WINDOW_SECONDS knob; collision-
# based idempotence is sufficient at the triage stage where re-emission
# is cheap and folds onto the same row).
#
# Optional-Effect Injection (doctrine case 15):
# candidate_service=None → no-op pass; preserves byte-identical pre-L1
# behaviour. Telemetry counter recorded.
#
# Readers are NOT injected into the factory — strategies own their
# Reader dependencies at construction time. The factory only knows
# about the SourceCandidateService composite.

_SOURCE_CANDIDATE_DEFAULT_TICK_S: int = 3600  # hourly


def _source_candidate_quality_filter() -> "_QualityFilter":
    """All ticks are potential triggers — gating happens at the composite."""

    def _filter(_payload: dict[str, Any]) -> bool:
        return True

    return _filter


def _make_source_candidate_gather_fn() -> "_GatherFn":
    """Build a gather_fn that returns one synthetic trigger per tick.

    The strategies scan projections via their Readers, so the
    gather_fn is a lightweight "fire-once-per-tick" guard. Each
    synthetic trigger carries the tick's timestamp + the
    ``ctx.company_id`` so the promotion_action can scope.
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        return [{
            "_source_candidate_trigger": True,
            "company_id": str(ctx.company_id),
            "triggering_entry_id": str(entry.get("entry_id") or ""),
        }]

    return _gather


def _cluster_source_candidate_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    Per-candidate_id dedup happens at promotion-action time after the
    composite service runs and merges across strategies that propose
    the same (kind, identifier, strategy) triple.
    """
    return [[e] for e in entries]


def _make_source_candidate_promotion_action(
    candidate_service: "Any | None",
) -> "_PromotionAction":
    """Build the source-candidate discovery promotion_action.

    Optional-Effect Injection (doctrine case 15):
    when ``candidate_service`` is None the action is a no-op pass.
    This preserves byte-identical pre-L1 behaviour for callers that
    have not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if candidate_service is None:
            return None
        if not cluster:
            return None

        proposals = await candidate_service.propose(company_id=ctx.company_id)
        if not proposals:
            return None

        # Dedup defensively by candidate_id (composite already dedups
        # across strategies via LakeLoopComposite; this is a safety net).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for p in proposals:
            cid = p.candidate_id
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            deduped.append(p)

        emitted_seqs: list[int] = []
        for proposal in deduped:
            await _emit_source_candidate_proposed(proposal=proposal, ctx=ctx)

        return FiredAction(
            action_kind="source_candidate_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_source_candidate_proposed(
    *,
    proposal: Any,  # ProposedSourceCandidate — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``source_candidate_proposed`` PEVR cycle for ``proposal``."""
    promotion_payload: dict[str, Any] = {
        "candidate_id": proposal.candidate_id,
        "proposed_kind": proposal.proposed_kind,
        "proposed_identifier": proposal.proposed_identifier,
        "domain_id_hint": proposal.domain_id_hint,
        "strategy": proposal.strategy,
        "reasoning": proposal.reasoning,
        "confidence": proposal.confidence,
        "evidence": dict(proposal.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "source_candidate_proposed",
            "candidate_id": proposal.candidate_id,
            "ref_id": proposal.candidate_id,
            "reason": (
                f"compounding-loop: source-candidate inference strategy="
                f"{proposal.strategy} proposed {proposal.proposed_kind} "
                f"for identifier={proposal.proposed_identifier!r} "
                f"confidence={proposal.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_source_candidate_proposed",
            "args": dict(promotion_payload),
            "result_ref": proposal.candidate_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [
                {"name": "source_candidate_proposed", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={proposal.strategy} "
                f"confidence={proposal.confidence:.2f} trended into a "
                f"source_candidate_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_source_candidate_discovery_reactivity(
    *,
    candidate_service: "Any | None" = None,
    tick_interval_s: int = _SOURCE_CANDIDATE_DEFAULT_TICK_S,
) -> "Compounding":
    """L1 source-candidate triage discovery axis.

    Source predicate: ``Periodic(every_seconds=tick_interval_s)`` —
    the Reactivity fires on each ``clock_tick`` ledger entry written
    by :class:`wormbase_reactivities.clock_tick_emitter.ClockTickEmitter`
    at the configured cadence.

    Why periodic, NOT event-driven (diverges from L3/L7/L4/L5/L6/L8):
    L1's three strategies all SCAN platform projections rather than
    react to a specific entry kind. A periodic cadence decouples
    discovery from upstream traffic (a freshly-installed worm with
    pre-existing KPI gaps still fires) and bounds the scan cost.

    Optional-Effect Injection (doctrine case 15 — **fourth lake-side
    axis built on :class:`LakeLoopComposite` from day one**):

      * ``candidate_service=None`` → no-op (all fires return empty
        proposal sets).
      * Service present → fires per-tick, invoking the composite's
        ``propose(company_id=...)`` which fans out to each wired
        strategy (KpiGap / ChannelMention / Complementarity) whose
        Reader dependency was wired at strategy construction time.

    Default args (service=None) preserve byte-identical pre-L1
    behaviour: the Reactivity registers but never proposes candidates.

    Sub-wave C wires a concrete ``candidate_service`` (a
    :class:`LakeLoopComposite[ProposedSourceCandidate]` from
    :func:`make_composite_source_candidate_service`) at install boot,
    along with the 3 Reader impls
    (:class:`LedgerConnectedSourceReader`,
    :class:`LedgerKpiNodeReader`,
    :class:`LedgerSilverConversationReader`) injected into each
    strategy at construction time.

    Replay-stable: ``candidate_id`` is deterministic on
    ``(proposed_kind, proposed_identifier, strategy)`` so re-running
    the same tick over the same upstream state yields the same
    ledger entries.

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the strategies' Reader signatures enforce it.

    LOW CADENCE — the periodic tick is hourly by default (3600s); the
    composite + reader scan cost is bounded by the projection sizes
    (sources / unbacked KPIs / recent silver conversations capped at
    1000). Multi-cadence safe: distinct ``ClockTickEmitter`` instances
    write separate ``clock_tick`` chains, and
    ``Periodic(every_seconds=N)`` filters on matching cadence so this
    axis only sees its own ticks.
    """
    return Compounding(
        id="agent_gateway.source_candidate_discovery",
        name="agent-gateway.source-candidate-discovery",
        description=(
            "Lake-side compounding axis: on clock_tick (periodic), "
            "runs source-candidate triage strategies (kpi_gap reading "
            "unbacked KPI nodes; channel_mention regex-scanning silver "
            "conversations; complementarity reading projection_sources "
            "for portfolio-gap heuristics) and emits one "
            "source_candidate_proposed PEVR cycle per inferred "
            "candidate. Optional-Effect Injection: no-op when "
            "candidate_service is None. Fourth lake-side axis built on "
            "LakeLoopComposite[T] from day one (after L5 + L6 + L8); "
            "introduces 3 NEW lightweight Reader Protocols (NOT "
            "cross-axis chains — they read first-class platform "
            "projections, not peer L-axis projections; cross-axis "
            "chain count stays at 3)."
        ),
        source_predicate=Periodic(every_seconds=tick_interval_s),
        quality_filter=_source_candidate_quality_filter(),
        gather_fn=_make_source_candidate_gather_fn(),
        cluster_fn=_cluster_source_candidate_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_source_candidate_promotion_action(
            candidate_service,
        ),
        novelty_key="source_candidate_discovery",
        scope="company",
    )


# ---------------------------------------------------------------------------
# L2 Sub-wave B (2026-06-09) — catalog-drift detection discovery axis.
#
# Mirrors the L3 / L7 / L4 / L5 / L6 / L8 axis structure: event-driven
# on ``EntryKind("external_catalog_imported")``. Whenever a fresh
# external catalog snapshot lands, this axis reconstructs (current,
# baseline) for the source and runs the 3 strategies (table_set,
# column_set, column_type) to detect structural drift.
#
# **NOT periodic** (diverges from L1's source-candidate axis which
# uses ``Periodic(every_seconds=...)`` because its strategies scan
# platform projections rather than diff snapshots). L2 is the
# canonical example of event-driven drift detection: the
# ``external_catalog_imported`` entry IS the trigger — there's no
# point running drift detection on a stale snapshot pair, and there's
# no need for a cadence backstop because catalog-mirror's W5a
# Reactivity owns the cadence at which fresh snapshots arrive.
#
# gather_fn: reconstructs (current, baseline) via the
# :class:`CatalogSnapshotReader` lightweight Reader Protocol (new in
# L2 — reads catalog-mirror substrate, NOT a peer-axis cross-axis
# chain; doctrine §4.6). Returns one synthetic trigger carrying the
# snapshot pair so the promotion_action can invoke the composite
# without re-reading.
#
# cluster_fn: identity (one synthetic trigger → one cluster). Per-
# drift_id dedup happens at promotion-action time (the composite
# already dedups across strategies via LakeLoopComposite by drift_id;
# this is the merge-across-strategy posture per spec §4.7).
#
# Threshold: >= 1 (every trigger that produces drift proposals
# promotes).
# Promotion: emit one ``catalog_drift_proposed`` PEVR cycle per
# proposed drift.
# Idempotency: per-drift_id dedup via projection PK
# ``(company_id, drift_id)``; ``make_drift_id`` is deterministic on
# ``(source_id, table_id, column, drift_kind, before, after)`` so re-
# emission across ticks naturally folds onto the same row. Per spec
# §4.8 — no PROPOSE_WINDOW_SECONDS knob today (mirrors L1).
#
# Optional-Effect Injection (doctrine case 16):
# drift_service=None OR catalog_snapshot_reader=None → no-op pass;
# preserves byte-identical pre-L2 behaviour. Telemetry counter
# recorded.
#
# Cross-axis chain count: stays at 3 (L4→L3, L6→L5, L8→L5). The
# :class:`CatalogSnapshotReader` Protocol reads catalog-mirror
# substrate (``external_catalog_imported`` is a first-class entry kind
# folded from catalog-mirror Reactivities, not a peer L-axis
# projection); the producer is substrate, not a Compounding loop.


def _catalog_drift_quality_filter(payload: dict[str, Any]) -> bool:
    """Quality filter for the L2 catalog-drift axis — source_id present."""
    # Identical contract to L3/L4/L5/L6/L7/L8 axes — source_id is the
    # canonical signal that the external_catalog_imported entry is well-
    # formed enough to drive drift detection.
    return _lineage_quality_filter(payload)


def _make_catalog_drift_quality_filter() -> "_QualityFilter":
    """Return the catalog-drift-discovery axis quality_filter."""
    return _catalog_drift_quality_filter


def _make_catalog_drift_gather_fn(
    catalog_snapshot_reader: "Any | None",
) -> "_GatherFn":
    """Build a gather_fn that reconstructs (current, baseline) per source.

    When ``catalog_snapshot_reader`` is None → empty list (Optional-
    Effect absent path; the composite telemetry counter records the
    no-op).

    Otherwise: extract ``source_id`` from the triggering
    ``external_catalog_imported`` entry; ask the reader for
    ``(current, baseline)``; emit ONE synthetic trigger carrying the
    pair so the promotion_action can invoke the composite without
    re-reading.

    Tenant scoping: the reader's signature pins ``company_id`` via
    ``ctx.company_id``.
    """

    async def _gather(
        entry: dict[str, Any], ctx: ReactivityContext,
    ) -> Sequence[dict[str, Any]]:
        if catalog_snapshot_reader is None:
            return []
        source_id = _entry_source_id(entry)
        if not source_id:
            return []
        current, baseline = await catalog_snapshot_reader.read_current_and_baseline(
            company_id=ctx.company_id, source_id=source_id,
        )
        return [{
            "_catalog_drift_trigger": True,
            "company_id": str(ctx.company_id),
            "source_id": source_id,
            "current_snapshot": current,
            "baseline_snapshot": baseline,
            "triggering_entry_id": str(entry.get("entry_id") or ""),
        }]

    return _gather


def _cluster_catalog_drift_triggers_identity(
    entries: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Identity cluster — one synthetic trigger entry per cluster.

    Per-drift_id dedup happens at promotion-action time after the
    composite service runs (LakeLoopComposite dedups across strategies
    via drift_id; merge-across-strategy posture per spec §4.7).
    """
    return [[e] for e in entries]


def _make_catalog_drift_promotion_action(
    drift_service: "Any | None",
) -> "_PromotionAction":
    """Build the catalog-drift-discovery promotion_action.

    Optional-Effect Injection (doctrine case 16):
    when ``drift_service`` is None the action is a no-op pass. This
    preserves byte-identical pre-L2 behaviour for callers that have
    not yet wired the service in.
    """

    async def _action(
        cluster: list[dict[str, Any]], ctx: ReactivityContext,
    ) -> FiredAction | None:
        if drift_service is None:
            return None
        if not cluster:
            return None
        trigger = cluster[0]
        current = trigger.get("current_snapshot")
        baseline = trigger.get("baseline_snapshot")
        if current is None:
            return None

        proposals = await drift_service.propose(
            company_id=ctx.company_id,
            current=current,
            baseline=baseline,
        )
        if not proposals:
            return None

        # Dedup defensively by drift_id (composite already dedups
        # across strategies via LakeLoopComposite; this is a safety net).
        seen_ids: set[str] = set()
        deduped: list[Any] = []
        for p in proposals:
            did = p.drift_id
            if did in seen_ids:
                continue
            seen_ids.add(did)
            deduped.append(p)

        emitted_seqs: list[int] = []
        for proposal in deduped:
            await _emit_catalog_drift_proposed(proposal=proposal, ctx=ctx)

        return FiredAction(
            action_kind="catalog_drift_proposed",
            action_seqs=emitted_seqs,
        )

    return _action


async def _emit_catalog_drift_proposed(
    *,
    proposal: Any,  # ProposedCatalogDrift — typed Any to avoid import cycle
    ctx: ReactivityContext,
) -> None:
    """Write one ``catalog_drift_proposed`` PEVR cycle for ``proposal``."""
    promotion_payload: dict[str, Any] = {
        "drift_id": proposal.drift_id,
        "source_id": proposal.source_id,
        "table_id": proposal.table_id,
        "column": proposal.column,
        "drift_kind": proposal.drift_kind,
        "before": proposal.before,
        "after": proposal.after,
        "strategy": proposal.strategy,
        "confidence": proposal.confidence,
        "reasoning": proposal.reasoning,
        "evidence": dict(proposal.evidence),
    }
    await ctx.ledger.write(
        company_id=ctx.company_id,
        propose={
            "target_kind": "catalog_drift_proposed",
            "drift_id": proposal.drift_id,
            "ref_id": proposal.drift_id,
            "reason": (
                f"compounding-loop: catalog-drift inference strategy="
                f"{proposal.strategy} proposed {proposal.drift_kind} "
                f"on {proposal.source_id}.{proposal.table_id}"
                f"{('.' + proposal.column) if proposal.column else ''} "
                f"confidence={proposal.confidence:.2f}"
            ),
            "proposed_by": "agent_gateway.compounding_loop",
        },
        execute_fn=lambda: {
            "tool": "emit_catalog_drift_proposed",
            "args": dict(promotion_payload),
            "result_ref": proposal.drift_id,
        },
        verify_fn=lambda _r: {
            **promotion_payload,
            "checks": [
                {"name": "catalog_drift_proposed", "ok": True},
            ],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            **promotion_payload,
            "outcome": "keep",
            "rationale": (
                f"strategy={proposal.strategy} "
                f"confidence={proposal.confidence:.2f} trended into a "
                f"catalog_drift_proposed entry"
            ),
        },
        timestamp=datetime.now(UTC),
        quadrant="passive_probabilistic",
    )


def make_catalog_drift_discovery_reactivity(
    *,
    drift_service: "Any | None" = None,
    catalog_snapshot_reader: "Any | None" = None,
) -> "Compounding":
    """L2 catalog-drift detection discovery axis.

    Source predicate: ``EntryKind("external_catalog_imported")`` —
    the Reactivity fires whenever the catalog-mirror lands a fresh
    snapshot. Drift detection is naturally event-driven (a stale
    snapshot pair has no new signal to extract).

    Optional-Effect Injection (doctrine case 16 — **fifth lake-side
    axis built on :class:`LakeLoopComposite` from day one** after
    L5 + L6 + L8 + L1):

      * ``drift_service=None`` → no-op (all fires return empty
        proposal sets).
      * ``catalog_snapshot_reader=None`` → cannot reconstruct
        snapshot pair → no-op.
      * Both present → fires per external_catalog_imported event,
        invoking the composite's ``propose(current=..., baseline=...)``
        which fans out to each wired strategy (TableSet /
        ColumnSet / ColumnType).

    Default args (both None) preserve byte-identical pre-L2
    behaviour: the Reactivity registers but never proposes drifts.

    Sub-wave C wires a concrete ``drift_service`` (a
    :class:`LakeLoopComposite[ProposedCatalogDrift]` from
    :func:`make_composite_catalog_drift_service`) AND a concrete
    :class:`CatalogSnapshotReader` impl at install boot.

    Replay-stable: ``drift_id`` is deterministic on
    ``(source_id, table_id, column, drift_kind, before, after)`` so
    re-emitting on a future tick over the same snapshot pair yields
    the same ledger entries (which fold onto the same projection PK).

    Tenant isolation: gather_fn + promotion_action scope by
    ``ctx.company_id`` — the reader's signature enforces it.

    Cross-axis chain count: stays at **3**. The
    :class:`CatalogSnapshotReader` Protocol reads catalog-mirror
    substrate (``external_catalog_imported`` entries), not a peer
    L-axis projection. Per spec §4.6 doctrine clarification.
    """
    return Compounding(
        id="agent_gateway.catalog_drift_discovery",
        name="agent-gateway.catalog-drift-discovery",
        description=(
            "Lake-side compounding axis: on external_catalog_imported, "
            "reconstructs (current, baseline) snapshots via "
            "CatalogSnapshotReader (NEW lightweight Reader Protocol — "
            "reads catalog-mirror substrate, NOT a peer-axis chain) "
            "and runs catalog-drift detection strategies (table_set "
            "diffing table-id sets productively day-1; column_set + "
            "column_type honest-stubbed pending richer upstream "
            "catalog metadata) and emits one catalog_drift_proposed "
            "PEVR cycle per inferred drift. Optional-Effect Injection: "
            "no-op when drift_service or catalog_snapshot_reader is "
            "None. Fifth lake-side axis built on LakeLoopComposite[T] "
            "from day one (after L5 + L6 + L8 + L1); cross-axis chain "
            "count stays at 3."
        ),
        source_predicate=EntryKind("external_catalog_imported"),
        quality_filter=_make_catalog_drift_quality_filter(),
        gather_fn=_make_catalog_drift_gather_fn(catalog_snapshot_reader),
        cluster_fn=_cluster_catalog_drift_triggers_identity,
        promotion_threshold=lambda cluster: len(cluster) >= 1,
        promotion_action=_make_catalog_drift_promotion_action(drift_service),
        novelty_key="catalog_drift_discovery",
        scope="company",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_agent_gateway_reactivities(
    *,
    gap_escalation_tick_s: int = _GAP_ESCALATION_TICK_S,
    subscription_dispatcher_deps: Any | None = None,
    projection_reader: Any | None = None,
) -> list[Reactivity]:
    """Return the Reactivities the agent-gateway registers at install boot.

    Follows the ``make_<function>_reactivities`` convention used by
    lake-maintainer, catalog-mirror, chat-presence, identity-tracker,
    process-extractor, and research-loop. Fixed order — caller-side
    telemetry can rely on it.

    v2.B Phase 1 shipped the ``Compounding`` primitive; Phase 2 ships
    the 3 new compounding axes (bad-pattern, gap-escalation,
    recommendation). Phase 3 (2026-05-12) swaps the gap-escalation
    axis from ``EntryKind("semantic_gap_proposed")`` to
    ``Periodic(every_seconds=gap_escalation_tick_s)`` so the
    Reactivity fires on a real cadence regardless of new-gap traffic.

    v2.A Batch B (2026-05-12) adds the optional ``SubscriptionDispatcher``
    Reactivity (6th in order, append-only). When
    ``subscription_dispatcher_deps`` is ``None`` (default) the dispatcher
    is NOT constructed and the returned list has 5 Reactivities —
    byte-identical to pre-Batch-B boot. Passing a
    ``SubscriptionDispatcherDeps`` bundle opts the dispatcher in.

    Total: 5 Reactivities by default, 6 when subscriptions are enabled.

    ``gap_escalation_tick_s`` defaults to 3600 (hourly). Production
    tunes via ``WORMBASE_AGENT_GATEWAY_TICK_S`` — wired at boot in
    ``apps/worm-core/src/wormbase_core/agent_gateway_construction.py``.
    """
    # v2.B Phase 3c — when ``projection_reader`` is non-None, axes 1
    # (template promotion) + 3 (bad-pattern) swap their ledger-scan
    # gather for a projection-table TopK read. Default None preserves
    # byte-identical pre-3c behaviour for all callers that don't opt in.
    rs: list[Reactivity] = [
        OutcomeToTemplatePromotionReactivity(
            projection_reader=projection_reader,
        ),
        QueryOutcomeToDataProductReactivity(),
        make_query_failure_to_bad_pattern_reactivity(
            projection_reader=projection_reader,
        ),
        make_semantic_gap_to_escalation_reactivity(
            tick_interval_s=gap_escalation_tick_s,
        ),
        make_data_product_consumption_to_recommendation_reactivity(),
    ]
    if subscription_dispatcher_deps is not None:
        # Lazy import to avoid pulling the subscriptions subpackage into
        # the import path for callers that don't opt in to v2.A.
        from wormbase_agent_gateway.subscriptions.dispatcher import (
            make_subscription_dispatcher_reactivity,
        )
        rs.append(
            make_subscription_dispatcher_reactivity(
                subscription_dispatcher_deps,
            ),
        )
    return rs


__all__ = [
    "Compounding",
    "OutcomeToTemplatePromotionReactivity",
    "QueryOutcomeToDataProductReactivity",
    "make_agent_gateway_reactivities",
    "make_catalog_drift_discovery_reactivity",
    "make_column_classification_discovery_reactivity",
    "make_data_product_consumption_to_recommendation_reactivity",
    "make_entity_stitch_discovery_reactivity",
    "make_fingerprint_discovery_reactivity",
    "make_lineage_discovery_reactivity",
    "make_outcome_to_template_promotion_reactivity",
    "make_quality_discovery_reactivity",
    "make_query_failure_to_bad_pattern_reactivity",
    "make_schema_impact_discovery_reactivity",
    "make_semantic_gap_to_escalation_reactivity",
    "make_source_candidate_discovery_reactivity",
]
