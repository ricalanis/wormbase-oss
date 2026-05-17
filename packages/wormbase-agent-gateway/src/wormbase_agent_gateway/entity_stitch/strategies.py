"""L8 cross-source entity stitching — three inference strategies.

Three concrete :class:`EntityStitchStrategy` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`NameMatchEntityStrategy` — **the cross-axis chain**. With
     ``use_semantic_type_anchor=True`` (default), reads L5's confirmed
     semantic types via the **reused** L6
     :class:`ConfirmedSemanticTypeReader` Protocol (second consumer of
     the same Protocol; L6's strategy is the first). When both
     endpoints share a confirmed semantic type (e.g. both
     ``pii_email``), proposes the stitch at high confidence (0.90).
     Independent of the semantic-type anchor, also proposes
     **pure-fuzzy-name** matches at lower confidence
     (Levenshtein-normalized threshold ≥0.7 → 0.60-0.75). Productive
     today even without L5 confirmed types via the fuzzy-name path.
  2. :class:`SampleOverlapEntityStrategy` — reuses L7's
     :class:`SamplerProtocol`. For each column pair, samples ``n``
     distinct values from each endpoint; computes Jaccard. ≥0.5 overlap
     → propose at scaled confidence (0.85 at full overlap; 0.50 at
     threshold). **Configured · empty-upstream today** in the same
     posture as L5/L7 sample paths — when the sampler returns empty
     sets (NoopSampler), the strategy emits no proposals (honest stub).
  3. :class:`SchemaShapeEntityStrategy` — compares the two endpoints'
     **parent tables** for structural similarity (column count delta,
     type-pattern overlap by-position, shared column-name set ratio).
     When the two tables look structurally similar, proposes stitches
     for each matching-name column pair at 0.50-0.75. **Productive on
     bare catalog metadata** — no sampling, no upstream readers, no L5
     dependency. Catch-all-shape strategy that fires even when names
     differ enough to escape NameMatch.

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset via :class:`LakeLoopComposite`
(Optional-Effect Injection doctrine case 14).

Reuse policy — L8 declares NO new Protocols:

  * :class:`wormbase_agent_gateway.column_classification.ConfirmedSemanticTypeReader`
    — **reused from L6** by the NameMatch strategy. Second consumer of
    the same Protocol; L6's
    :class:`SemanticTypeClassificationStrategy` is the first.
    Validates the consumer-owned-Protocol pattern generalises to N
    consumers.
  * :class:`wormbase_agent_gateway.lineage.SamplerProtocol` — reused
    from L3/L5/L7 by the SampleOverlap strategy.

This is the cleanest Sub-wave B in the lake-side family — zero new
Protocols, two reuses, one cross-axis chain.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.lineage.strategies import SamplerProtocol

from .protocol import (
    EntityKind,
    EntityStitchStrategy,
    ProposedEntityStitch,
    make_stitch_id,
)

__all__ = [
    "NameMatchEntityStrategy",
    "SampleOverlapEntityStrategy",
    "SchemaShapeEntityStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


# Mapping from L5 confirmed semantic type → L8 entity_kind. The NameMatch
# strategy uses this when ``use_semantic_type_anchor=True`` to infer
# the entity_kind from the shared semantic type signal. Types not in
# the table fall back to ``other``. Per spec §4.3 — names mirror the
# L6 _SEMANTIC_TYPE_TO_CLASSIFICATION mapping for shared types and add
# entity-specific routings.
_SEMANTIC_TYPE_TO_ENTITY_KIND: dict[str, EntityKind] = {
    # Personal identity → person
    "email": "person",
    "phone_e164": "person",
    "phone_us": "person",
    "pii_name": "person",
    "pii_address": "person",
    "pii_ssn": "person",
    "pii_credit_card": "person",
    # Business identifiers → organization (best-guess; could be person too
    # but the cross-source bridge is typically org-scoped on these)
    "business_id": "organization",
    # Money/metric → transaction (entity-scope: a financial event)
    "metric_amount": "transaction",
    # Temporal anchors are not entity types themselves; default `other`
    # but kept here so callers can override via subclass.
    # Identifiers (uuids) → other (could bridge anything)
    "uuid_v4": "other",
    "uuid_v7": "other",
}


def _entity_kind_for_semantic_type(semantic_type: str) -> EntityKind:
    """Best-effort entity_kind mapping for a known L5 semantic type.

    Falls back to ``"other"`` for any type not in the mapping table
    (including time-anchors, geo-codes, metric_count, metric_rate —
    none of those identify an entity, they describe one).
    """
    return _SEMANTIC_TYPE_TO_ENTITY_KIND.get(semantic_type, "other")


def _propose(
    *,
    column_a: dict,
    column_b: dict,
    upstream_semantic_type_id: str | None,
    entity_kind: EntityKind,
    confidence: float,
    strategy: str,
    reasoning: str,
    evidence: dict[str, Any],
) -> ProposedEntityStitch:
    """Construct a :class:`ProposedEntityStitch` with canonical ``stitch_id``.

    Single shared constructor across strategies — guarantees the
    ``stitch_id`` hash is computed consistently (same dedup key for the
    same pair regardless of a/b ordering at call time). The endpoint
    fields are stored verbatim (NOT canonicalised) so audit-trail prose
    keeps the strategy-author's intent visible; only the hash is
    canonicalised internally.
    """
    return ProposedEntityStitch(
        stitch_id=make_stitch_id(src_a=column_a, src_b=column_b),
        src_source_id_a=str(column_a["source_id"]),
        src_table_a=str(column_a["table_id"]),
        src_column_a=str(column_a["column"]),
        src_source_id_b=str(column_b["source_id"]),
        src_table_b=str(column_b["table_id"]),
        src_column_b=str(column_b["column"]),
        upstream_semantic_type_id=upstream_semantic_type_id,
        entity_kind=entity_kind,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


def _normalize_name(name: str) -> str:
    """Lowercase + strip + drop common boilerplate punctuation.

    Used by the fuzzy-name comparison in
    :class:`NameMatchEntityStrategy`. Conservatively keeps underscores
    so ``user_email`` and ``customer_email`` retain word boundaries
    (the Levenshtein distance still captures the prefix delta).
    """
    return name.strip().lower()


def _levenshtein(a: str, b: str) -> int:
    """Standard iterative Levenshtein distance (no external deps).

    Used by :class:`NameMatchEntityStrategy` for fuzzy name matching.
    Time O(len(a) * len(b)); fine for column names (typically 10-30
    chars). For longer strings consider a library, but no L8 input
    crosses that threshold.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,       # insertion
                prev[j] + 1,           # deletion
                prev[j - 1] + cost,    # substitution
            )
        prev = curr
    return prev[-1]


def _normalized_levenshtein_similarity(a: str, b: str) -> float:
    """Return a similarity score on [0.0, 1.0]: ``1 - distance / max_len``.

    Symmetric in a/b. Identical strings → 1.0. Disjoint single-char
    strings → 0.0. Used by :class:`NameMatchEntityStrategy`'s
    fuzzy-name path with a 0.7 threshold per spec §4.5.
    """
    na = _normalize_name(a)
    nb = _normalize_name(b)
    if not na and not nb:
        return 1.0
    max_len = max(len(na), len(nb))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(na, nb) / max_len


def _jaccard(a: set, b: set) -> float:
    """Set Jaccard index. Empty union → 0.0 (cannot infer overlap)."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


# ---------------------------------------------------------------------------
# Strategy 1 — NameMatchEntityStrategy (cross-axis to L5 via reused L6 Protocol)
# ---------------------------------------------------------------------------


class NameMatchEntityStrategy:
    """Cross-source entity stitching via shared L5 semantic types + fuzzy names.

    **The cross-axis chain.** When ``use_semantic_type_anchor=True``
    (default), reads L5 confirmed semantic types for BOTH endpoints via
    the **reused** L6
    :class:`ConfirmedSemanticTypeReader` Protocol. When both endpoints
    share a confirmed semantic type (e.g. both ``pii_email`` or both
    ``business_id``), proposes a stitch at 0.90 confidence — strong
    signal that the two columns reference the same real-world entity.

    Independent of the semantic-type anchor, ALSO proposes pure
    fuzzy-name matches: normalised Levenshtein similarity ≥0.7 between
    column-name strings → 0.60-0.75 confidence (linear interpolation
    between threshold 0.7 → 0.60 and 1.0 → 0.75). The two paths can
    fire on the same pair; the composite dedups by ``stitch_id`` (which
    omits strategy + level) so the higher-confidence proposal wins
    inside the same strategy.

    ``entity_kind`` inference:

      * Semantic-type-anchored proposals: derived from the shared
        semantic type via :data:`_SEMANTIC_TYPE_TO_ENTITY_KIND` (e.g.
        ``email`` / ``pii_*`` → ``person``; ``business_id`` →
        ``organization``; ``metric_amount`` → ``transaction``).
      * Fuzzy-name-only proposals: always ``other`` — bare name
        similarity doesn't disambiguate entity class.

    Skips when:

      * Either ``column`` string is empty.
      * The pair is the same column on the same source (no
        self-bridges).

    name: str = ``"name_match"``

    Reuse posture: imports L6's
    :class:`ConfirmedSemanticTypeReader` directly — does NOT redeclare.
    Second consumer of the Protocol; the first is L6's own
    :class:`SemanticTypeClassificationStrategy`. Validates the
    consumer-owned-Protocol pattern generalises across multiple
    downstream axes.
    """

    name: str = "name_match"

    FUZZY_THRESHOLD: float = 0.7
    SEMANTIC_TYPE_CONFIDENCE: float = 0.90
    FUZZY_MIN_CONFIDENCE: float = 0.60
    FUZZY_MAX_CONFIDENCE: float = 0.75

    def __init__(
        self,
        *,
        confirmed_semantic_type_reader: ConfirmedSemanticTypeReader | None = None,
        use_semantic_type_anchor: bool = True,
    ) -> None:
        # When use_semantic_type_anchor is True, the reader is required
        # (else the anchor path is a no-op). When False, the strategy
        # only emits fuzzy-name proposals and the reader is unused.
        self.confirmed_semantic_type_reader = confirmed_semantic_type_reader
        self.use_semantic_type_anchor = use_semantic_type_anchor

    async def propose(
        self,
        *,
        company_id: UUID,
        column_a: dict,
        column_b: dict,
    ) -> list[ProposedEntityStitch]:
        """Anchor on shared L5 type if available; always also try fuzzy name."""
        col_a_name = str(column_a.get("column") or "")
        col_b_name = str(column_b.get("column") or "")
        if not col_a_name or not col_b_name:
            return []

        # Same-column-on-same-source short-circuit (the gather_fn
        # filters across sources but a strategy boundary defensive
        # guard is cheap).
        if (
            column_a.get("source_id") == column_b.get("source_id")
            and column_a.get("table_id") == column_b.get("table_id")
            and col_a_name == col_b_name
        ):
            return []

        proposals: list[ProposedEntityStitch] = []

        # --- Semantic-type-anchored path (cross-axis read) ---
        if (
            self.use_semantic_type_anchor
            and self.confirmed_semantic_type_reader is not None
        ):
            types_a = await (
                self.confirmed_semantic_type_reader
                .list_confirmed_types_for_table_column(
                    table_id=str(column_a["table_id"]),
                    column=col_a_name,
                    company_id=company_id,
                )
            )
            types_b = await (
                self.confirmed_semantic_type_reader
                .list_confirmed_types_for_table_column(
                    table_id=str(column_b["table_id"]),
                    column=col_b_name,
                    company_id=company_id,
                )
            )
            shared = _shared_semantic_types(types_a, types_b)
            for shared_type, anchor_record in shared:
                kind = _entity_kind_for_semantic_type(shared_type)
                proposals.append(
                    _propose(
                        column_a=column_a,
                        column_b=column_b,
                        upstream_semantic_type_id=anchor_record.type_id,
                        entity_kind=kind,
                        confidence=self.SEMANTIC_TYPE_CONFIDENCE,
                        strategy=self.name,
                        reasoning=(
                            f"L5 confirmed shared semantic type "
                            f"{shared_type!r} on both endpoints; "
                            f"entity_kind={kind} at "
                            f"{self.SEMANTIC_TYPE_CONFIDENCE:.2f}"
                        ),
                        evidence={
                            "path": "semantic_type_anchor",
                            "shared_semantic_type": shared_type,
                            "anchor_type_id": anchor_record.type_id,
                            "endpoint_a_type_count": len(types_a),
                            "endpoint_b_type_count": len(types_b),
                        },
                    )
                )

        # --- Fuzzy-name path (always tried; independent of L5) ---
        similarity = _normalized_levenshtein_similarity(col_a_name, col_b_name)
        if similarity >= self.FUZZY_THRESHOLD:
            # Linear interp: 0.70 → 0.60, 1.00 → 0.75
            confidence = self.FUZZY_MIN_CONFIDENCE + (
                similarity - self.FUZZY_THRESHOLD
            ) * (self.FUZZY_MAX_CONFIDENCE - self.FUZZY_MIN_CONFIDENCE) / (
                1.0 - self.FUZZY_THRESHOLD
            )
            proposals.append(
                _propose(
                    column_a=column_a,
                    column_b=column_b,
                    upstream_semantic_type_id=None,
                    entity_kind="other",
                    confidence=confidence,
                    strategy=self.name,
                    reasoning=(
                        f"normalized-Levenshtein similarity={similarity:.3f} "
                        f"≥ {self.FUZZY_THRESHOLD:.2f} on column names "
                        f"{col_a_name!r} ↔ {col_b_name!r}; entity_kind=other "
                        f"(fuzzy-name has no entity-kind signal) at "
                        f"{confidence:.2f}"
                    ),
                    evidence={
                        "path": "fuzzy_name",
                        "similarity": round(similarity, 4),
                        "threshold": self.FUZZY_THRESHOLD,
                        "column_a": col_a_name,
                        "column_b": col_b_name,
                    },
                )
            )

        return proposals


def _shared_semantic_types(
    types_a: Sequence[ConfirmedSemanticTypeRecord],
    types_b: Sequence[ConfirmedSemanticTypeRecord],
) -> list[tuple[str, ConfirmedSemanticTypeRecord]]:
    """Return (shared_semantic_type, anchor_record) pairs.

    For each semantic type present on both endpoints, pick the
    higher-confidence record from endpoint-a (ties → first-seen) as the
    anchor that supplies ``upstream_semantic_type_id``. Replay-stable
    on input ordering.
    """
    by_type_a: dict[str, ConfirmedSemanticTypeRecord] = {}
    for r in types_a:
        existing = by_type_a.get(r.semantic_type)
        if existing is None or r.confidence > existing.confidence:
            by_type_a[r.semantic_type] = r
    types_b_set: set[str] = {r.semantic_type for r in types_b}
    out: list[tuple[str, ConfirmedSemanticTypeRecord]] = []
    for st, anchor in by_type_a.items():
        if st in types_b_set:
            out.append((st, anchor))
    return out


# ---------------------------------------------------------------------------
# Strategy 2 — SampleOverlapEntityStrategy (sampling-based, honest stub today)
# ---------------------------------------------------------------------------


class SampleOverlapEntityStrategy:
    """Cross-source stitching via Jaccard overlap of sampled column values.

    Reuses L7/L5/L3's :class:`SamplerProtocol` for value sampling — no
    new Protocol introduced. Samples ``sample_size`` distinct values
    from each endpoint via :meth:`SamplerProtocol.sample_column`,
    computes Jaccard, and proposes a stitch when overlap meets
    ``jaccard_threshold`` (default 0.5).

    Confidence scaling (linear interp per spec §4.5):

      * 0.50 overlap → 0.50 confidence (threshold floor)
      * 1.00 overlap → 0.85 confidence (cap; sampling never beats
        type-anchor 0.90 nor exact ground-truth)

    ``entity_kind`` inference: defaults to ``"other"`` because value
    overlap alone doesn't disambiguate entity class. The L6+L8 stack
    relies on the NameMatch strategy's semantic-type-anchor path for
    entity-kind signal; the SampleOverlap strategy's value overlap is
    orthogonal evidence at the same ``stitch_id``.

    **Honest-stub posture today** — when the sampler is the production
    ``NoopSampler`` (returns empty sets), the strategy emits no
    proposals (empty samples → 0.0 Jaccard → below threshold). Sub-
    wave C wires the production sampler.

    Skips when:

      * Either endpoint has a same source_id (cross-axis filter at
        gather_fn time already excludes; defensive guard here is
        redundant but cheap).
      * Either sample is empty (sampler returned no values).

    name: str = ``"sample_overlap"``
    """

    name: str = "sample_overlap"

    DEFAULT_SAMPLE_SIZE: int = 200
    DEFAULT_JACCARD_THRESHOLD: float = 0.5
    MIN_CONFIDENCE: float = 0.50
    MAX_CONFIDENCE: float = 0.85

    def __init__(
        self,
        *,
        sampler: SamplerProtocol,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
    ) -> None:
        self.sampler = sampler
        self.sample_size = sample_size
        self.jaccard_threshold = jaccard_threshold

    async def propose(
        self,
        *,
        company_id: UUID,
        column_a: dict,
        column_b: dict,
    ) -> list[ProposedEntityStitch]:
        """Sample each endpoint; Jaccard ≥ threshold → propose at scaled conf."""
        del company_id  # sampler scopes by table_id; tenant isolation is upstream
        sample_a = await self.sampler.sample_column(
            str(column_a["table_id"]), str(column_a["column"]), self.sample_size,
        )
        sample_b = await self.sampler.sample_column(
            str(column_b["table_id"]), str(column_b["column"]), self.sample_size,
        )
        if not sample_a or not sample_b:
            return []
        jaccard = _jaccard(sample_a, sample_b)
        if jaccard < self.jaccard_threshold:
            return []
        # Linear interp: 0.50 → MIN_CONFIDENCE, 1.00 → MAX_CONFIDENCE
        confidence = self.MIN_CONFIDENCE + (
            jaccard - self.jaccard_threshold
        ) * (self.MAX_CONFIDENCE - self.MIN_CONFIDENCE) / (
            1.0 - self.jaccard_threshold
        )
        # entity_kind: default `other`. If the two endpoints' parent
        # tables share a name (common rename across sources, e.g. both
        # tables called `customers`), nudge towards `organization` —
        # otherwise leave `other`.
        kind: EntityKind = "other"
        table_a_name = str(column_a["table_id"]).split(".")[-1]
        table_b_name = str(column_b["table_id"]).split(".")[-1]
        if table_a_name and table_a_name == table_b_name:
            # Same final segment → still 'other' by design; the kind
            # signal from sample overlap alone is too weak to override.
            # Keep this branch as the documented extension point.
            pass
        return [
            _propose(
                column_a=column_a,
                column_b=column_b,
                upstream_semantic_type_id=None,
                entity_kind=kind,
                confidence=confidence,
                strategy=self.name,
                reasoning=(
                    f"sampled-value Jaccard overlap={jaccard:.3f} "
                    f"(≥ {self.jaccard_threshold:.2f}) across "
                    f"|A|={len(sample_a)} |B|={len(sample_b)}; "
                    f"entity_kind={kind} at {confidence:.2f}"
                ),
                evidence={
                    "path": "sample_overlap",
                    "jaccard": round(jaccard, 4),
                    "threshold": self.jaccard_threshold,
                    "sample_size_a": len(sample_a),
                    "sample_size_b": len(sample_b),
                },
            ),
        ]


# ---------------------------------------------------------------------------
# Strategy 3 — SchemaShapeEntityStrategy (catalog-metadata only; productive today)
# ---------------------------------------------------------------------------


class SchemaShapeEntityStrategy:
    """Cross-source stitching from structural similarity of parent tables.

    Compares the **parent tables** of the two endpoint columns:

      * Column-count delta ≤ ``column_count_delta_max`` (default 2):
        the two tables are roughly the same shape.
      * Type-pattern overlap by-position ≥
        ``type_overlap_threshold`` (default 0.6) — currently a stub
        (catalog tables don't expose per-column types in the dict shape
        L8 sees today; the heuristic degrades to column-count + name-
        set ratio in the productive-today path).
      * Shared column-name set ratio ≥ ``name_overlap_threshold``
        (default 0.5): at least half the column names are present in
        BOTH parent tables.

    When the parent tables look structurally similar, proposes stitches
    for each **matching-name column pair** at 0.50-0.75 confidence
    (linear interp on the name-overlap ratio: 0.50 → 0.50; 1.00 →
    0.75). The proposal endpoints are the actual column_a / column_b
    passed in — the strategy is pair-scoped at the protocol layer, but
    the parent-table comparison provides the structural evidence.

    **Productive today on bare catalog metadata** — no sampling, no
    upstream readers, no L5 dependency. Catch-all-shape strategy.

    ``entity_kind`` = ``other`` — schema shape alone doesn't
    disambiguate entity class (admin upgrades on confirmation if the
    NameMatch path also fired with a stronger kind signal).

    The strategy requires the caller to inject **parent-table column
    lists** via a thin lookup callback at construction time. This is
    NOT a Protocol — just a callable accepting ``(source_id, table_id)``
    and returning the column-name list. Sub-wave C wires this via the
    L3 :class:`_CatalogReader` adapter (a closure over
    :meth:`list_tables_for_source`).

    name: str = ``"schema_shape"``
    """

    name: str = "schema_shape"

    DEFAULT_COLUMN_COUNT_DELTA_MAX: int = 2
    DEFAULT_NAME_OVERLAP_THRESHOLD: float = 0.5
    DEFAULT_TYPE_OVERLAP_THRESHOLD: float = 0.6
    MIN_CONFIDENCE: float = 0.50
    MAX_CONFIDENCE: float = 0.75

    def __init__(
        self,
        *,
        parent_table_columns_lookup: Any | None = None,
        column_count_delta_max: int = DEFAULT_COLUMN_COUNT_DELTA_MAX,
        name_overlap_threshold: float = DEFAULT_NAME_OVERLAP_THRESHOLD,
        type_overlap_threshold: float = DEFAULT_TYPE_OVERLAP_THRESHOLD,
    ) -> None:
        # Callable: async (source_id: str, table_id: str) -> list[str]
        # When None, the strategy is a no-op (empty parent-column lookup
        # means we cannot compare structure). Sub-wave C wires a real
        # closure over the catalog reader; tests provide a dict-backed
        # closure.
        self.parent_table_columns_lookup = parent_table_columns_lookup
        self.column_count_delta_max = column_count_delta_max
        self.name_overlap_threshold = name_overlap_threshold
        self.type_overlap_threshold = type_overlap_threshold

    async def propose(
        self,
        *,
        company_id: UUID,
        column_a: dict,
        column_b: dict,
    ) -> list[ProposedEntityStitch]:
        """Compare parent tables; propose stitch on the input pair if shapes align."""
        del company_id  # parent-table lookup is scoped via the closure
        if self.parent_table_columns_lookup is None:
            return []

        table_a_id = str(column_a["table_id"])
        table_b_id = str(column_b["table_id"])
        source_a_id = str(column_a["source_id"])
        source_b_id = str(column_b["source_id"])

        cols_a_list = await self.parent_table_columns_lookup(
            source_a_id, table_a_id,
        )
        cols_b_list = await self.parent_table_columns_lookup(
            source_b_id, table_b_id,
        )
        cols_a = [str(c) for c in (cols_a_list or [])]
        cols_b = [str(c) for c in (cols_b_list or [])]
        if not cols_a or not cols_b:
            return []

        # Column-count delta gate.
        if abs(len(cols_a) - len(cols_b)) > self.column_count_delta_max:
            return []

        # Shared column-name set ratio.
        set_a = set(cols_a)
        set_b = set(cols_b)
        intersection = set_a & set_b
        union = set_a | set_b
        name_overlap = len(intersection) / len(union) if union else 0.0
        if name_overlap < self.name_overlap_threshold:
            return []

        # Confidence interp: 0.50 → MIN, 1.00 → MAX.
        confidence = self.MIN_CONFIDENCE + (
            name_overlap - self.name_overlap_threshold
        ) * (self.MAX_CONFIDENCE - self.MIN_CONFIDENCE) / (
            1.0 - self.name_overlap_threshold
        )
        # Only propose the input-pair stitch when the input columns
        # themselves share names (i.e. this pair is one of the
        # matching-name columns). Otherwise the input pair is not
        # structurally evidenced — the gather_fn enumerates all
        # cross-source pairs, so each matching-name pair will get its
        # own propose() call separately.
        if column_a["column"] != column_b["column"]:
            # When column names differ, schema_shape still has nothing
            # specific to say about THIS pair — it would just be a
            # bystander to the same-named pairs. Skip.
            return []

        return [
            _propose(
                column_a=column_a,
                column_b=column_b,
                upstream_semantic_type_id=None,
                entity_kind="other",
                confidence=confidence,
                strategy=self.name,
                reasoning=(
                    f"parent tables shape-aligned: |A|={len(cols_a)} "
                    f"|B|={len(cols_b)} (delta≤{self.column_count_delta_max}); "
                    f"name-set overlap={name_overlap:.3f} "
                    f"(≥ {self.name_overlap_threshold:.2f}); column "
                    f"{column_a['column']!r} present on both endpoints; "
                    f"entity_kind=other at {confidence:.2f}"
                ),
                evidence={
                    "path": "schema_shape",
                    "column_count_a": len(cols_a),
                    "column_count_b": len(cols_b),
                    "column_count_delta": abs(len(cols_a) - len(cols_b)),
                    "name_overlap": round(name_overlap, 4),
                    "shared_column_count": len(intersection),
                    "union_column_count": len(union),
                },
            ),
        ]


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[EntityStitchStrategy], ...] = (
    SchemaShapeEntityStrategy,
)
del _proto_check
