"""L7 quality-check discovery — three inference strategies.

Three concrete :class:`QualityCheckProposalService` impls, ranked by
``(speed, cost, ground-truth-proximity)``:

  1. :class:`SchemaPatternStrategy` — metadata-only, fastest, mid
     confidence. Heuristics on column type, nullability, naming.
  2. :class:`DbtTestsStrategy` — metadata-only, highest confidence
     when the manifest is present. Lifts dbt ``not_null``, ``unique``,
     ``accepted_values``, ``dbt_utils.row_count``, and
     ``dbt_utils.test_freshness`` tests out of the mirrored manifest.
  3. :class:`HistoricalStatsStrategy` — requires N≥3 historical
     snapshots of column-level statistics. Stubbed today (Wave 1
     catalog mirror doesn't yet emit column-level stats; gated by
     ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED`` in Sub-wave C).

Each strategy is independently constructable + testable. The composite
in :mod:`composite` consumes any subset (Optional-Effect Injection
doctrine case 10).
"""
from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
)

from .protocol import (
    CatalogTable,
    ProposedQualityCheck,
    QualityCheckKind,
    QualityCheckProposalService,
    make_check_id,
)

__all__ = [
    "ConfirmedSemanticTypeReader",
    "ConfirmedSemanticTypeRecord",
    "DbtTestReader",
    "DbtTestsStrategy",
    "HistoricalStatsReader",
    "HistoricalStatsStrategy",
    "SchemaPatternStrategy",
    "SemanticTypeQualityCheckStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _propose(
    *,
    table: CatalogTable,
    column: str | None,
    check_kind: QualityCheckKind,
    config: dict[str, Any],
    confidence: float,
    strategy: str,
    reasoning: str,
    evidence: dict[str, Any],
    upstream_semantic_type_id: str | None = None,
) -> ProposedQualityCheck:
    """Construct a :class:`ProposedQualityCheck` with the canonical
    ``check_id`` precomputed via :func:`make_check_id`.

    Single shared constructor across strategies — guarantees the
    ``check_id`` hash is computed consistently (same dedup key).

    ``upstream_semantic_type_id`` is the L5→L7 cross-axis link; defaults
    to ``None`` so the 3 pre-existing strategies (schema_pattern /
    dbt_tests / historical_stats) round-trip byte-identical. The 4th
    strategy (semantic_type) sets it to the originating L5 type_id.
    """
    return ProposedQualityCheck(
        check_id=make_check_id(
            table_id=table.table_id,
            check_kind=check_kind,
            column=column,
            normalized_config=config,
        ),
        table_id=table.table_id,
        column=column,
        check_kind=check_kind,
        config=config,
        confidence=confidence,
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
        upstream_semantic_type_id=upstream_semantic_type_id,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — SchemaPatternStrategy
# ---------------------------------------------------------------------------


class SchemaPatternStrategy:
    """Infers quality checks from column metadata + naming patterns.

    No data sampled — fastest strategy. Suitable for high-cadence
    catalog imports. Reads ``CatalogTable.metadata`` for per-column
    stats; when stats are absent (Wave 1 catalog mirror today), the
    naming + nullability heuristics still fire.

    Per-column heuristics (per spec §3.3):

      * Column marked ``NOT NULL`` but observed-NULL in stats →
        ``not_null`` check at ``0.85``.
      * Column named ``id`` or ``*_id`` (suffix) with high cardinality
        (or no cardinality info) → ``unique`` check at ``0.80``.
      * Column with timestamp-style name (``*_at``, ``*_ts``,
        ``*_time``) or type → ``freshness`` check at ``0.70``.
      * Column with low cardinality (< ``low_cardinality_max``,
        default 10) → ``enum_membership`` at ``0.65``.

    A stop-list filters trivial names where the naming signal is too
    weak (``name``, ``description``, ``status`` etc. — present
    everywhere). Override via constructor.

    ``CatalogTable.metadata`` shape expected (all optional — strategy
    degrades gracefully when keys are absent):

      * ``columns`` — list of per-column dicts with keys
        ``name``, ``type``, ``nullable``, ``observed_null_ratio``,
        ``distinct_count`` (the last two are Wave-1-future).

    name: str = ``"schema_pattern"``
    """

    name: str = "schema_pattern"

    DEFAULT_STOP_LIST: frozenset[str] = frozenset({
        "name",
        "description",
        "status",
        "kind",
        "type",
    })

    DEFAULT_TIMESTAMP_TYPES: frozenset[str] = frozenset({
        "timestamp",
        "timestamptz",
        "datetime",
        "date",
        "time",
    })

    def __init__(
        self,
        *,
        stop_list: frozenset[str] | None = None,
        low_cardinality_max: int = 10,
        freshness_default_hours: int = 24,
        timestamp_types: frozenset[str] | None = None,
    ) -> None:
        self.stop_list = (
            stop_list if stop_list is not None else self.DEFAULT_STOP_LIST
        )
        self.low_cardinality_max = low_cardinality_max
        self.freshness_default_hours = freshness_default_hours
        self.timestamp_types = (
            timestamp_types
            if timestamp_types is not None
            else self.DEFAULT_TIMESTAMP_TYPES
        )

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """Walk the table's columns, emit checks per heuristic."""
        del sample_size  # unused — metadata-only strategy
        del company_id  # unused — schema-pattern is table-scoped, not tenant-scoped
        proposals: list[ProposedQualityCheck] = []

        # ``metadata.columns`` is the preferred per-column blob; when
        # absent, we still fire naming-based heuristics off
        # ``table.columns``.
        meta_columns: dict[str, dict[str, Any]] = {}
        raw_meta_cols = table.metadata.get("columns") if table.metadata else None
        if isinstance(raw_meta_cols, list):
            for col_meta in raw_meta_cols:
                if isinstance(col_meta, dict):
                    nm = col_meta.get("name")
                    if isinstance(nm, str):
                        meta_columns[nm] = col_meta

        for col in table.columns:
            col_l = col.lower()
            if col_l in self.stop_list:
                continue
            col_meta = meta_columns.get(col, {})
            col_type = str(col_meta.get("type", "")).lower()
            nullable = col_meta.get("nullable")
            observed_null = col_meta.get("observed_null_ratio")
            distinct_count = col_meta.get("distinct_count")

            # Heuristic 1 — NOT NULL + observed-NULL → not_null
            if (
                nullable is False
                and isinstance(observed_null, (int, float))
                and observed_null > 0
            ):
                proposals.append(
                    _propose(
                        table=table,
                        column=col,
                        check_kind="not_null",
                        config={},
                        confidence=0.85,
                        strategy=self.name,
                        reasoning=(
                            f"column {col!r} marked NOT NULL but observed "
                            f"null_ratio={observed_null:.4f} → propose "
                            f"not_null check"
                        ),
                        evidence={
                            "nullable": False,
                            "observed_null_ratio": float(observed_null),
                            "match_kind": "not_null_violation",
                        },
                    )
                )

            # Heuristic 2 — id / *_id with high cardinality → unique.
            # "High cardinality" interpreted permissively here: when
            # distinct_count is unknown, we still fire on the id-name
            # signal alone (catalog stats land Wave 1+).
            is_id_named = col_l == "id" or col_l.endswith("_id")
            if is_id_named:
                high_card = True
                if isinstance(distinct_count, int) and distinct_count > 0:
                    # If we have an explicit count, only fire when it's
                    # genuinely large (>1 distinct value). A 1-value
                    # column is clearly NOT unique.
                    high_card = distinct_count >= 2
                if high_card:
                    proposals.append(
                        _propose(
                            table=table,
                            column=col,
                            check_kind="unique",
                            config={},
                            confidence=0.80,
                            strategy=self.name,
                            reasoning=(
                                f"column {col!r} matches id-naming "
                                f"pattern → propose unique check"
                            ),
                            evidence={
                                "naming_pattern": (
                                    "id" if col_l == "id" else "*_id"
                                ),
                                "distinct_count": (
                                    int(distinct_count)
                                    if isinstance(distinct_count, int)
                                    else None
                                ),
                            },
                        )
                    )

            # Heuristic 3 — timestamp name OR timestamp type → freshness
            is_ts_named = (
                col_l.endswith("_at")
                or col_l.endswith("_ts")
                or col_l.endswith("_time")
                or col_l in {"created", "updated", "deleted"}
            )
            is_ts_typed = col_type in self.timestamp_types
            if is_ts_named or is_ts_typed:
                proposals.append(
                    _propose(
                        table=table,
                        column=col,
                        check_kind="freshness",
                        config={"max_age_hours": self.freshness_default_hours},
                        confidence=0.70,
                        strategy=self.name,
                        reasoning=(
                            f"column {col!r} looks timestamp-like "
                            f"(naming={is_ts_named}, type={col_type!r}) "
                            f"→ propose freshness check at "
                            f"{self.freshness_default_hours}h"
                        ),
                        evidence={
                            "ts_named": is_ts_named,
                            "ts_typed": is_ts_typed,
                            "column_type": col_type,
                            "freshness_default_hours": (
                                self.freshness_default_hours
                            ),
                        },
                    )
                )

            # Heuristic 4 — low cardinality → enum_membership
            if (
                isinstance(distinct_count, int)
                and 0 < distinct_count <= self.low_cardinality_max
            ):
                # We don't know the actual allowed values here without
                # sampling (which schema_pattern doesn't do); leave the
                # set empty — admin fills it on confirm, or
                # historical-stats refines it.
                proposals.append(
                    _propose(
                        table=table,
                        column=col,
                        check_kind="enum_membership",
                        config={"allowed_values": []},
                        confidence=0.65,
                        strategy=self.name,
                        reasoning=(
                            f"column {col!r} has low cardinality "
                            f"(distinct={distinct_count}) → propose "
                            f"enum_membership check"
                        ),
                        evidence={
                            "distinct_count": int(distinct_count),
                            "low_cardinality_max": self.low_cardinality_max,
                        },
                    )
                )

        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — DbtTestsStrategy
# ---------------------------------------------------------------------------


# Mapping of dbt test names to QualityCheckKind + confidence. Open enum
# at the dbt side (custom tests, dbt_utils tests, dbt_expectations, ...);
# we surface the canonical core + a couple of common dbt_utils tests.
_DBT_TEST_MAP: dict[str, tuple[QualityCheckKind, float]] = {
    "not_null": ("not_null", 0.99),
    "unique": ("unique", 0.99),
    "accepted_values": ("enum_membership", 0.99),
    "dbt_utils.row_count": ("row_count_range", 0.95),
    "dbt_utils.test_freshness": ("freshness", 0.95),
}


class DbtTestReader(Protocol):
    """Abstraction over dbt manifest test access.

    The concrete impl wraps Wave-1's wormbase-catalog-mirror dbt
    manifest mirror (``external_lineage_imported`` carries dbt model
    metadata). The Protocol shape keeps the strategy testable without
    spinning a manifest fixture.

    Returns lists of test descriptors; each test is a dict carrying
    enough to identify it:

      * ``test_name``: the dbt test identifier (``"not_null"``,
        ``"accepted_values"``, ``"dbt_utils.row_count"``, ...)
      * ``column``: the target column (``None`` for table-grain tests
        like ``dbt_utils.row_count``)
      * ``config``: any test-specific config (e.g.
        ``{"values": ["a", "b"]}`` for accepted_values)

    Unknown test names are skipped by the strategy.
    """

    async def get_tests_for_model(
        self, model_id: str,
    ) -> list[dict[str, Any]]:
        """Return the dbt test descriptors attached to ``model_id``."""
        ...


class DbtTestsStrategy:
    """Infers quality checks from dbt manifest test declarations.

    Highest-confidence strategy when the manifest is present — dbt
    tests are explicit author intent. Only fires for catalog tables
    with ``source_kind == "dbt"`` (so non-dbt tables don't pay a
    no-result manifest read).

    Maps dbt test names to :data:`QualityCheckKind` via
    :data:`_DBT_TEST_MAP`. Unknown test names are skipped.

    name: str = ``"dbt_tests"``
    """

    name: str = "dbt_tests"

    def __init__(self, *, manifest_reader: DbtTestReader) -> None:
        self.manifest_reader = manifest_reader

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """Read dbt tests for the model; map each to a proposal."""
        del sample_size  # unused — manifest strategy is metadata-only
        del company_id  # unused — dbt-test reader is model-scoped, not tenant-scoped
        if table.source_kind != "dbt":
            return []

        tests = await self.manifest_reader.get_tests_for_model(
            table.table_id,
        )
        proposals: list[ProposedQualityCheck] = []
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_name = test.get("test_name")
            if not isinstance(test_name, str):
                continue
            mapping = _DBT_TEST_MAP.get(test_name)
            if mapping is None:
                continue
            check_kind, confidence = mapping

            raw_column = test.get("column")
            column: str | None = (
                raw_column if isinstance(raw_column, str) and raw_column
                else None
            )

            raw_config = test.get("config") or {}
            test_config = raw_config if isinstance(raw_config, dict) else {}
            check_config = _normalize_dbt_config(
                check_kind=check_kind, test_config=test_config,
            )

            proposals.append(
                _propose(
                    table=table,
                    column=column,
                    check_kind=check_kind,
                    config=check_config,
                    confidence=confidence,
                    strategy=self.name,
                    reasoning=(
                        f"dbt test {test_name!r} on column={column!r} → "
                        f"propose {check_kind} check at confidence="
                        f"{confidence:.2f}"
                    ),
                    evidence={
                        "dbt_test_name": test_name,
                        "dbt_config": dict(test_config),
                        "column": column,
                    },
                )
            )
        return proposals


def _normalize_dbt_config(
    *, check_kind: QualityCheckKind, test_config: dict[str, Any],
) -> dict[str, Any]:
    """Translate dbt test config into the canonical check-kind config.

    Per :data:`QualityCheckKind` docstring:

      * ``accepted_values`` (dbt) → ``{"allowed_values": [...]}``
      * ``dbt_utils.row_count`` → ``{"min_rows": <int>, "max_rows": <int>}``
        (dbt carries ``min_value`` / ``max_value``)
      * ``dbt_utils.test_freshness`` → ``{"max_age_hours": <int>}``
      * ``not_null`` / ``unique`` → ``{}``

    Unknown / partial configs degrade gracefully — missing keys map to
    sensible defaults so the resulting check_id is still stable.
    """
    if check_kind == "enum_membership":
        values = test_config.get("values") or test_config.get("allowed_values")
        if isinstance(values, list):
            return {"allowed_values": [str(v) for v in values]}
        return {"allowed_values": []}
    if check_kind == "row_count_range":
        min_rows = test_config.get("min_value") or test_config.get("min_rows")
        max_rows = test_config.get("max_value") or test_config.get("max_rows")
        out: dict[str, Any] = {}
        if isinstance(min_rows, (int, float)):
            out["min_rows"] = int(min_rows)
        if isinstance(max_rows, (int, float)):
            out["max_rows"] = int(max_rows)
        return out
    if check_kind == "freshness":
        max_age = (
            test_config.get("max_age_hours")
            or test_config.get("loaded_at_field_hours")
        )
        if isinstance(max_age, (int, float)):
            return {"max_age_hours": int(max_age)}
        return {"max_age_hours": 24}
    # not_null / unique — no per-test config needed.
    return {}


# ---------------------------------------------------------------------------
# Strategy 3 — HistoricalStatsStrategy
# ---------------------------------------------------------------------------


class HistoricalStatsReader(Protocol):
    """Abstraction over historical catalog-snapshot reads.

    The concrete impl wraps Wave-1's wormbase-catalog-mirror snapshot
    history (each ``external_catalog_imported`` ledger entry carries a
    per-import snapshot). Sub-wave C wires this against the catalog
    mirror; today the catalog mirror doesn't yet emit column-level
    stats (Wave-1-future).

    Per-table snapshot grammar (Wave-1-future):

      * ``row_count``: int — total rows at snapshot time
      * ``latest_timestamp_age_hours``: float — age of the latest row
        in any timestamp column, in hours
      * ``columns``: list of per-column dicts with keys
        ``name`` and ``distinct_values`` (a set of observed values)
    """

    async def get_snapshots_for_table(
        self, table_id: str,
    ) -> list[dict[str, Any]]:
        """Return historical snapshot blobs for ``table_id`` (newest last)."""
        ...


class HistoricalStatsStrategy:
    """Infers quality checks from historical catalog snapshots.

    Requires N≥``min_snapshots`` (default 3) historical snapshots of
    column-level stats. Uses statistical estimators:

      * Stable mean + p95 row count over the window →
        ``row_count_range`` proposal (config = computed band)
      * Stable latest-timestamp drift → ``freshness`` threshold
        proposal (config = max observed age × buffer)
      * Stable distinct-value set across snapshots →
        ``enum_membership`` proposal (config = the union of values)

    **Stubbed today** — Wave 1 catalog mirror doesn't yet emit
    column-level stats. The strategy is structurally complete and the
    code path runs, but with the current catalog mirror it sees empty
    snapshots and returns ``[]``. Sub-wave C gates this strategy
    behind ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED`` to make the
    honest-stub posture auditable.

    name: str = ``"historical_stats"``
    """

    name: str = "historical_stats"

    def __init__(
        self,
        *,
        reader: HistoricalStatsReader,
        min_snapshots: int = 3,
        row_count_buffer_ratio: float = 0.2,
        freshness_buffer_ratio: float = 1.5,
    ) -> None:
        self.reader = reader
        self.min_snapshots = min_snapshots
        self.row_count_buffer_ratio = row_count_buffer_ratio
        self.freshness_buffer_ratio = freshness_buffer_ratio

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """Walk the historical snapshots; emit checks per stable signal."""
        del sample_size  # unused — we read historical snapshots, not data
        del company_id  # unused — historical-stats reader is table-scoped
        snapshots = await self.reader.get_snapshots_for_table(table.table_id)
        if not snapshots or len(snapshots) < self.min_snapshots:
            return []

        proposals: list[ProposedQualityCheck] = []

        # --- row_count_range ---
        row_counts = [
            s.get("row_count") for s in snapshots
            if isinstance(s.get("row_count"), (int, float))
        ]
        if len(row_counts) >= self.min_snapshots:
            rc_values = [float(r) for r in row_counts]
            rc_mean = sum(rc_values) / len(rc_values)
            rc_min = int(min(rc_values) * (1 - self.row_count_buffer_ratio))
            rc_max = int(max(rc_values) * (1 + self.row_count_buffer_ratio))
            # Clamp min_rows non-negative.
            rc_min = max(rc_min, 0)
            proposals.append(
                _propose(
                    table=table,
                    column=None,
                    check_kind="row_count_range",
                    config={"min_rows": rc_min, "max_rows": rc_max},
                    confidence=0.75,
                    strategy=self.name,
                    reasoning=(
                        f"row_count stable over {len(rc_values)} snapshots "
                        f"(mean={rc_mean:.0f}); propose range "
                        f"[{rc_min}, {rc_max}]"
                    ),
                    evidence={
                        "n_snapshots": len(rc_values),
                        "row_count_mean": rc_mean,
                        "row_count_min": min(rc_values),
                        "row_count_max": max(rc_values),
                        "buffer_ratio": self.row_count_buffer_ratio,
                    },
                )
            )

        # --- freshness ---
        ages_hours = [
            s.get("latest_timestamp_age_hours") for s in snapshots
            if isinstance(s.get("latest_timestamp_age_hours"), (int, float))
        ]
        if len(ages_hours) >= self.min_snapshots:
            ah = [float(a) for a in ages_hours]
            max_age = max(ah)
            buffered = int(max_age * self.freshness_buffer_ratio)
            buffered = max(buffered, 1)
            proposals.append(
                _propose(
                    table=table,
                    column=None,
                    check_kind="freshness",
                    config={"max_age_hours": buffered},
                    confidence=0.75,
                    strategy=self.name,
                    reasoning=(
                        f"latest-row age stable over {len(ah)} snapshots "
                        f"(max_observed_age_h={max_age:.1f}); propose "
                        f"freshness threshold {buffered}h"
                    ),
                    evidence={
                        "n_snapshots": len(ah),
                        "max_observed_age_hours": max_age,
                        "buffer_ratio": self.freshness_buffer_ratio,
                    },
                )
            )

        # --- enum_membership ---
        # For each column, intersect distinct_values across snapshots;
        # if the intersection is non-empty AND stable (set equality
        # across snapshots), propose enum_membership.
        per_col_values: dict[str, list[set[str]]] = {}
        for s in snapshots:
            cols = s.get("columns") or []
            if not isinstance(cols, list):
                continue
            for col_blob in cols:
                if not isinstance(col_blob, dict):
                    continue
                cname = col_blob.get("name")
                vals = col_blob.get("distinct_values")
                if not isinstance(cname, str) or not isinstance(vals, (list, set)):
                    continue
                per_col_values.setdefault(cname, []).append(
                    {str(v) for v in vals},
                )

        for cname, value_sets in per_col_values.items():
            if len(value_sets) < self.min_snapshots:
                continue
            # Stable iff every snapshot's distinct set is identical.
            first = value_sets[0]
            if not first:
                continue
            stable = all(s == first for s in value_sets[1:])
            if not stable:
                continue
            sorted_values = sorted(first)
            proposals.append(
                _propose(
                    table=table,
                    column=cname,
                    check_kind="enum_membership",
                    config={"allowed_values": sorted_values},
                    confidence=0.80,
                    strategy=self.name,
                    reasoning=(
                        f"column {cname!r} has stable distinct value set "
                        f"({len(sorted_values)} values) across "
                        f"{len(value_sets)} snapshots → propose "
                        f"enum_membership"
                    ),
                    evidence={
                        "n_snapshots": len(value_sets),
                        "value_set_size": len(sorted_values),
                        "stable": True,
                    },
                )
            )

        return proposals


# ---------------------------------------------------------------------------
# Strategy 4 — SemanticTypeQualityCheckStrategy (cross-axis to L5 via reused L6 Protocol)
# ---------------------------------------------------------------------------


# Mapping from L5 confirmed semantic_type → tuple of L7 QualityCheckKinds
# to propose. The selection is conservative: only check kinds that are
# canonical and unambiguous for each semantic type. Types not in the
# table (or future additions) silently emit no proposals (kept narrow on
# purpose — admin can always confirm a schema-pattern proposal).
#
# Rationale per kind:
#
#   * ``not_null`` — every identity/reference type SHOULD be non-null.
#   * ``unique`` — types that act as primary keys / unique references
#     (email, uuid, business_id). Types whose uniqueness varies (phone
#     can be shared between users; pii_name has duplicates) skip it.
#
# Confidence is the same across all proposals from this strategy (0.85)
# — L5 confirmation is a strong signal but not as strong as a dbt-test
# (0.99). Kept conservative; admin tunes via /lake/quality.
_SEMANTIC_TYPE_TO_CHECK_KINDS: dict[str, tuple[QualityCheckKind, ...]] = {
    # Personal identity — email is canonical primary-key material; uuid
    # variants likewise. pii_name has duplicates so unique is omitted.
    "email": ("not_null", "unique"),
    "pii_name": ("not_null",),
    "phone_e164": ("not_null",),
    "phone_us": ("not_null",),
    "pii_address": ("not_null",),
    "pii_ssn": ("not_null", "unique"),
    "pii_credit_card": ("not_null", "unique"),
    # Identifiers — UUIDs are unique by construction.
    "uuid_v4": ("not_null", "unique"),
    "uuid_v7": ("not_null", "unique"),
    # Business identifiers — typically primary keys.
    "business_id": ("not_null", "unique"),
    # url / metric_amount / metric_count / metric_rate / time_* / geo_*
    # are deliberately absent — they don't carry canonical not_null /
    # unique semantics. Operators can still get checks on them via the
    # schema_pattern strategy.
}


class SemanticTypeQualityCheckStrategy:
    """L5→L7 cross-axis strategy — proposes canonical quality checks
    from L5-confirmed semantic types.

    **The 4th cross-axis chain**. Reads L5 confirmed semantic types via
    the **reused** L6 :class:`ConfirmedSemanticTypeReader` Protocol
    (3rd consumer of the same Protocol — L6 is 1st, L8 is 2nd, L7 is
    3rd). When a column is confirmed as ``email``, proposes both
    ``not_null`` AND ``unique``. When confirmed as ``phone_e164`` /
    ``phone_us`` / ``pii_name``, proposes ``not_null`` only
    (uniqueness varies for those types). And so on per
    :data:`_SEMANTIC_TYPE_TO_CHECK_KINDS`.

    Confidence: 0.85 (high — L5 confirmation is strong signal, but the
    canonical schema-pattern + dbt_tests strategies still dominate when
    they fire).

    ``upstream_semantic_type_id`` is threaded onto every proposal so
    the dashboard renders a "view L5 semantic type →" cross-axis link
    on the /lake/quality row.

    Reuse posture: imports L6's
    :class:`ConfirmedSemanticTypeReader` directly — does NOT redeclare
    a Protocol. **3rd consumer of the same Protocol** (1st = L6's own
    SemanticTypeClassificationStrategy; 2nd = L8's NameMatchEntityStrategy
    semantic-type-anchor path; 3rd = this strategy). Validates the
    consumer-owned-Protocol pattern generalises to N consumers.

    Skips when:

      * ``company_id`` is None (the strategy needs a tenant scope —
        callers that don't carry one short-circuit to empty proposals).
      * No L5-confirmed types for the column (the reader returns []).
      * The confirmed semantic_type is not in
        :data:`_SEMANTIC_TYPE_TO_CHECK_KINDS` (conservative — unknown
        types yield no proposals; the other strategies still fire).

    name: str = ``"semantic_type"``
    """

    name: str = "semantic_type"
    DEFAULT_CONFIDENCE: float = 0.85

    def __init__(
        self,
        *,
        confirmed_semantic_type_reader: ConfirmedSemanticTypeReader,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.confirmed_semantic_type_reader = confirmed_semantic_type_reader
        self.confidence = confidence

    async def propose_checks(
        self,
        *,
        table: CatalogTable,
        sample_size: int = 1000,
        company_id: UUID | None = None,
    ) -> list[ProposedQualityCheck]:
        """For each column, look up confirmed L5 types; emit canonical checks."""
        del sample_size  # cross-axis strategy is metadata-only
        if company_id is None:
            # Strategy requires tenant scope — short-circuit when not provided.
            # Callers that don't carry company_id keep working unchanged
            # (no proposals from this strategy, other strategies still
            # fire normally via the composite).
            return []
        if not table.columns:
            return []

        proposals: list[ProposedQualityCheck] = []
        for column in table.columns:
            if not column:
                continue
            records = await (
                self.confirmed_semantic_type_reader
                .list_confirmed_types_for_table_column(
                    table_id=table.table_id,
                    column=column,
                    company_id=company_id,
                )
            )
            if not records:
                continue
            # When multiple semantic types are confirmed on the same
            # column (e.g. ``user_email`` confirmed as both ``email``
            # and ``pii_name``), we emit proposals from each — the
            # composite dedups by check_id, so the strongest (highest-
            # confidence) wins on overlap.
            for record in records:
                check_kinds = _SEMANTIC_TYPE_TO_CHECK_KINDS.get(
                    record.semantic_type,
                )
                if not check_kinds:
                    continue
                for check_kind in check_kinds:
                    proposals.append(
                        _propose(
                            table=table,
                            column=column,
                            check_kind=check_kind,
                            config={},
                            confidence=self.confidence,
                            strategy=self.name,
                            reasoning=(
                                f"L5 confirmed semantic_type="
                                f"{record.semantic_type!r} on column "
                                f"{column!r} → propose {check_kind} "
                                f"check at {self.confidence:.2f} "
                                f"(canonical check for this semantic "
                                f"type per L5→L7 cross-axis chain)"
                            ),
                            evidence={
                                "upstream_semantic_type_id": record.type_id,
                                "semantic_type": record.semantic_type,
                                "upstream_type_confidence": record.confidence,
                                "upstream_type_strategy": record.strategy,
                            },
                            upstream_semantic_type_id=record.type_id,
                        )
                    )
        return proposals


# Update _propose to accept upstream_semantic_type_id. We extend the
# helper via a thin override below so the existing strategies stay
# byte-identical (they don't pass the new field).


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[QualityCheckProposalService], ...] = (
    SchemaPatternStrategy,
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    SemanticTypeQualityCheckStrategy,
)
del _proto_check
