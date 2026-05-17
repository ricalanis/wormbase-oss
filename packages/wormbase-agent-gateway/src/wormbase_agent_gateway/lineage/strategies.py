"""L3 lineage-discovery — three inference strategies.

Three concrete :class:`LineageInferenceService` impls, ranked by
``(speed, cost, ground-truth-proximity)``:

  1. :class:`NamingHeuristicStrategy` — metadata-only, fastest, lowest
     confidence; column-name matches with a stop-list filter.
  2. :class:`DbtManifestStrategy` — metadata-only, near-ground-truth
     when present; lifts ``ref()`` / ``source()`` calls out of the
     mirrored dbt manifest.
  3. :class:`SampleOverlapStrategy` — sampling, most expensive, highest
     confidence on opaque columns; Jaccard similarity of sampled column
     values.

Each strategy is independently constructable + testable. The composite
in :mod:`composite` consumes any subset (Optional-Effect Injection
doctrine case 9).
"""
from __future__ import annotations

from typing import Any, Protocol

from .protocol import CatalogTable, InferredEdge, LineageInferenceService

__all__ = [
    "DbtManifestReader",
    "DbtManifestStrategy",
    "NamingHeuristicStrategy",
    "SampleOverlapStrategy",
    "SamplerProtocol",
]


# ---------------------------------------------------------------------------
# Strategy 1 — NamingHeuristicStrategy
# ---------------------------------------------------------------------------


class NamingHeuristicStrategy:
    """Infers edges from column-name matches with stop-list filtering.

    No data sampled — fastest strategy. Suitable for high-cadence
    catalog imports.

    Match grammar (descending confidence):

      * Exact non-stop-list match (``customer_id == customer_id`` and
        ``"customer_id"`` is NOT in the stop list) → ``0.85``.
      * Edit-distance ``<= edit_distance_max`` (default 2) on names
        ≥ ``min_shared_prefix`` chars (default 3, handles
        ``cust_id`` ↔ ``customer_id``) → ``0.7``.
      * Substring match (one column name is a suffix/prefix of the
        other, length ≥ ``min_shared_prefix``) → ``0.6``.

    Stop-list rejects "common" columns where naming match is too weak a
    signal (``id``, ``created_at``, ``name`` etc. — present everywhere).
    Override via constructor.

    name: str = ``"naming_heuristic"``
    """

    name: str = "naming_heuristic"

    DEFAULT_STOP_LIST: frozenset[str] = frozenset({
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "name",
        "description",
        "type",
        "kind",
        "status",
    })

    def __init__(
        self,
        *,
        stop_list: frozenset[str] | None = None,
        edit_distance_max: int = 2,
        min_shared_prefix: int = 3,
    ) -> None:
        self.stop_list = (
            stop_list if stop_list is not None else self.DEFAULT_STOP_LIST
        )
        self.edit_distance_max = edit_distance_max
        self.min_shared_prefix = min_shared_prefix

    async def infer_edges(
        self,
        *,
        source_table: CatalogTable,
        candidate_targets: list[CatalogTable],
        sample_size: int = 1000,
    ) -> list[InferredEdge]:
        """For each source column, find best-match columns in each target."""
        del sample_size  # unused — naming strategy is metadata-only
        out: list[InferredEdge] = []
        for tgt in candidate_targets:
            if tgt.table_id == source_table.table_id:
                continue  # same table; not a lineage edge
            for src_col in source_table.columns:
                src_l = src_col.lower()
                for tgt_col in tgt.columns:
                    tgt_l = tgt_col.lower()
                    confidence, reason_tag = self._score(src_l, tgt_l)
                    if confidence == 0.0:
                        continue
                    out.append(
                        InferredEdge(
                            src_table_id=source_table.table_id,
                            src_column=src_col,
                            tgt_table_id=tgt.table_id,
                            tgt_column=tgt_col,
                            confidence=confidence,
                            strategy=self.name,
                            reasoning=(
                                f"naming match ({reason_tag}): "
                                f"{src_col!r} ~ {tgt_col!r}"
                            ),
                            evidence={
                                "match_kind": reason_tag,
                                "src_column": src_col,
                                "tgt_column": tgt_col,
                                "stop_list_size": len(self.stop_list),
                            },
                        )
                    )
        return out

    def _score(self, src: str, tgt: str) -> tuple[float, str]:
        """Return ``(confidence, match_tag)`` or ``(0.0, "")`` for no match.

        Lowercased inputs assumed. ``match_tag`` ∈ {"exact",
        "edit_distance", "substring"}.
        """
        if src == tgt:
            if src in self.stop_list:
                return 0.0, ""
            return 0.85, "exact"
        # Edit-distance fallback
        if (
            len(src) >= self.min_shared_prefix
            and len(tgt) >= self.min_shared_prefix
        ):
            dist = _edit_distance(src, tgt, cap=self.edit_distance_max + 1)
            if dist <= self.edit_distance_max:
                # Both endpoints non-stop-list to fire
                if src not in self.stop_list and tgt not in self.stop_list:
                    return 0.7, "edit_distance"
        # Substring fallback (one is suffix/prefix of the other)
        if (
            len(src) >= self.min_shared_prefix
            and len(tgt) >= self.min_shared_prefix
            and (src.endswith(tgt) or tgt.endswith(src)
                 or src.startswith(tgt) or tgt.startswith(src))
        ):
            if src not in self.stop_list and tgt not in self.stop_list:
                return 0.6, "substring"
        return 0.0, ""


def _edit_distance(a: str, b: str, *, cap: int) -> int:
    """Levenshtein distance, capped at ``cap`` (returns ``cap`` once exceeded).

    Capping turns the O(mn) DP into early-out on long mismatched strings.
    Used by NamingHeuristicStrategy where ``cap`` is typically 2-3.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) >= cap:
        return cap
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    prev = list(range(la + 1))
    for i, cb in enumerate(b, start=1):
        curr = [i] + [0] * la
        row_min = curr[0]
        for j, ca in enumerate(a, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost, # substitution
            )
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min >= cap:
            return cap
        prev = curr
    return prev[la]


# ---------------------------------------------------------------------------
# Strategy 2 — SampleOverlapStrategy
# ---------------------------------------------------------------------------


class SamplerProtocol(Protocol):
    """Abstraction over actual data source sampling (so tests can mock)."""

    async def sample_column(
        self, table_id: str, column: str, n: int,
    ) -> set[str]:
        """Return up to ``n`` distinct non-null sampled string values."""
        ...

    async def estimate_table_size(self, table_id: str) -> int:
        """Return a row-count estimate (need not be exact)."""
        ...


class SampleOverlapStrategy:
    """Infers edges from Jaccard similarity of sampled column values.

    Most expensive strategy — requires actual data reads via the
    injected sampler. Gated in production by env knob; the Compounding
    factory can leave this strategy ``None`` on the composite to disable.

    Confidence: ``0.55`` at Jaccard 0.5; scales linearly to ``0.95`` at
    Jaccard 0.95+. Below ``jaccard_threshold`` → not proposed.

    Skips when:

      * Source column has < ``value_richness_min`` non-null distinct
        values (sample too thin to trust).
      * Either table has > ``max_table_size`` rows (sampling cost
        unbounded — defer to other strategies).
      * Source and target tables share the same ``table_id``.

    name: str = ``"sample_overlap"``
    """

    name: str = "sample_overlap"

    def __init__(
        self,
        *,
        sampler: SamplerProtocol,
        jaccard_threshold: float = 0.5,
        value_richness_min: int = 10,
        max_table_size: int = 10_000_000,
    ) -> None:
        self.sampler = sampler
        self.jaccard_threshold = jaccard_threshold
        self.value_richness_min = value_richness_min
        self.max_table_size = max_table_size

    async def infer_edges(
        self,
        *,
        source_table: CatalogTable,
        candidate_targets: list[CatalogTable],
        sample_size: int = 1000,
    ) -> list[InferredEdge]:
        """Sample rows from src + each tgt; Jaccard per (src, tgt) pair."""
        # Pre-filter on table size — source first.
        src_size = await self.sampler.estimate_table_size(source_table.table_id)
        if src_size > self.max_table_size:
            return []

        out: list[InferredEdge] = []
        # Per-column sample cache for the source — sampled once per src column.
        src_samples: dict[str, set[str]] = {}
        for src_col in source_table.columns:
            sample = await self.sampler.sample_column(
                source_table.table_id, src_col, sample_size,
            )
            src_samples[src_col] = sample

        for tgt in candidate_targets:
            if tgt.table_id == source_table.table_id:
                continue
            tgt_size = await self.sampler.estimate_table_size(tgt.table_id)
            if tgt_size > self.max_table_size:
                continue
            for tgt_col in tgt.columns:
                tgt_sample = await self.sampler.sample_column(
                    tgt.table_id, tgt_col, sample_size,
                )
                for src_col, src_sample in src_samples.items():
                    if len(src_sample) < self.value_richness_min:
                        continue
                    if not tgt_sample:
                        continue
                    jaccard = _jaccard(src_sample, tgt_sample)
                    if jaccard < self.jaccard_threshold:
                        continue
                    confidence = _jaccard_to_confidence(jaccard)
                    intersection_n = len(src_sample & tgt_sample)
                    union_n = len(src_sample | tgt_sample)
                    out.append(
                        InferredEdge(
                            src_table_id=source_table.table_id,
                            src_column=src_col,
                            tgt_table_id=tgt.table_id,
                            tgt_column=tgt_col,
                            confidence=confidence,
                            strategy=self.name,
                            reasoning=(
                                f"sample overlap: Jaccard={jaccard:.3f} "
                                f"({intersection_n}/{union_n}) sampled_n="
                                f"{sample_size}"
                            ),
                            evidence={
                                "sample_overlap_ratio": round(jaccard, 4),
                                "intersection_n": intersection_n,
                                "union_n": union_n,
                                "sampled_n": sample_size,
                                "src_sample_richness": len(src_sample),
                                "tgt_sample_richness": len(tgt_sample),
                            },
                        )
                    )
        return out


def _jaccard(a: set[str], b: set[str]) -> float:
    """Set Jaccard index. Empty union → 0.0 (cannot infer overlap)."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


def _jaccard_to_confidence(jaccard: float) -> float:
    """Map Jaccard ≥ 0.5 to confidence on [0.55, 0.95].

    Linear interpolation: ``0.5 → 0.55``, ``1.0 → 1.05`` clipped to
    ``0.95``. The clip keeps confidence < 1.0 so sampling never
    out-confidences a dbt-manifest hit (0.99).
    """
    confidence = 0.55 + (jaccard - 0.5) * (0.95 - 0.55) / (1.0 - 0.5)
    return min(0.95, max(0.0, confidence))


# ---------------------------------------------------------------------------
# Strategy 3 — DbtManifestStrategy
# ---------------------------------------------------------------------------


class DbtManifestReader(Protocol):
    """Abstraction over dbt manifest access.

    The concrete impl wraps Wave-1's wormbase-catalog-mirror dbt
    manifest mirror. The Protocol shape keeps the strategy testable
    without spinning a manifest fixture.
    """

    async def get_refs_for_model(self, model_id: str) -> list[str]:
        """Return downstream-target table_ids the model refs via ``ref()``."""
        ...

    async def get_source_refs(self, model_id: str) -> list[str]:
        """Return upstream-source table_ids the model refs via ``source()``."""
        ...


class DbtManifestStrategy:
    """Infers edges from dbt manifest ``ref()`` / ``source()`` calls.

    Highest-confidence strategy — explicit dbt refs are near-ground-truth.
    Requires the dbt manifest to be mirrored by Wave-1's
    ``wormbase-catalog-mirror``; the strategy only fires for catalog
    tables with ``source_kind == "dbt"``.

    Confidence: ``0.99`` — dbt refs are near-ground-truth (the lineage
    is literally in the model SQL).

    name: str = ``"dbt_manifest"``
    """

    name: str = "dbt_manifest"

    def __init__(self, *, manifest_reader: DbtManifestReader) -> None:
        self.manifest_reader = manifest_reader

    async def infer_edges(
        self,
        *,
        source_table: CatalogTable,
        candidate_targets: list[CatalogTable],
        sample_size: int = 1000,
    ) -> list[InferredEdge]:
        """For each ref/source in manifest, propose an edge.

        The strategy is direction-aware: ``ref()`` calls point at this
        model's *upstream* dependencies (sources), so the proposed edge
        is ``ref_target → source_table``. ``source()`` calls likewise
        produce ``raw_source → source_table`` edges. Each edge is
        whole-table (``src_column = tgt_column = None``) because the
        manifest doesn't carry column-grain refs.
        """
        del sample_size  # unused — manifest strategy is metadata-only
        if source_table.source_kind != "dbt":
            return []

        candidate_ids = {tgt.table_id for tgt in candidate_targets}
        out: list[InferredEdge] = []

        # ref() — model-to-model edges
        for upstream_id in await self.manifest_reader.get_refs_for_model(
            source_table.table_id,
        ):
            if upstream_id not in candidate_ids:
                continue
            if upstream_id == source_table.table_id:
                continue
            out.append(
                InferredEdge(
                    src_table_id=upstream_id,
                    src_column=None,
                    tgt_table_id=source_table.table_id,
                    tgt_column=None,
                    confidence=0.99,
                    strategy=self.name,
                    reasoning=(
                        f"dbt ref(): {source_table.table_id} depends on "
                        f"{upstream_id} via ref()"
                    ),
                    evidence={
                        "ref_kind": "ref",
                        "upstream_model": upstream_id,
                        "downstream_model": source_table.table_id,
                    },
                )
            )

        # source() — raw-source-to-model edges
        for upstream_id in await self.manifest_reader.get_source_refs(
            source_table.table_id,
        ):
            if upstream_id not in candidate_ids:
                continue
            if upstream_id == source_table.table_id:
                continue
            out.append(
                InferredEdge(
                    src_table_id=upstream_id,
                    src_column=None,
                    tgt_table_id=source_table.table_id,
                    tgt_column=None,
                    confidence=0.99,
                    strategy=self.name,
                    reasoning=(
                        f"dbt source(): {source_table.table_id} reads "
                        f"raw source {upstream_id}"
                    ),
                    evidence={
                        "ref_kind": "source",
                        "upstream_source": upstream_id,
                        "downstream_model": source_table.table_id,
                    },
                )
            )

        return out


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[LineageInferenceService], ...] = (
    NamingHeuristicStrategy,
    DbtManifestStrategy,
    SampleOverlapStrategy,
)
del _proto_check
