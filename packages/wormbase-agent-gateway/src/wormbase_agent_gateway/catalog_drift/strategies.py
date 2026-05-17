"""L2 catalog-drift detection — three drift-detection strategies.

Three concrete :class:`CatalogDriftStrategy` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`TableSetDriftStrategy` — productive day-1
     Diffs ``{t.table_id for t in current.tables}`` vs the baseline's
     equivalent set. For each added/removed table_id, emits a
     proposal with ``drift_kind ∈ {"table_added", "table_removed"}``,
     confidence 0.90.

  2. :class:`ColumnSetDriftStrategy` — configured · empty-upstream
     Per-table column-set diff. **Honest stub today**: when
     ``current.tables[*].columns == ()`` (today's reality per Sub-wave
     A handoff — ``external_catalog_imported`` carries no per-column
     structure), returns ``[]`` with honest reasoning. **Productive
     once richer emitters land**: same code path emits
     ``column_added`` / ``column_removed`` proposals at 0.85
     confidence per column diff.

  3. :class:`ColumnTypeDriftStrategy` — configured · empty-upstream
     Per-column type diff. **Honest stub today** for the same reason
     as ColumnSet. **Productive once richer emitters land**: emits
     ``column_type_changed`` proposals at 0.80 confidence per type
     diff.

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset via :class:`LakeLoopComposite`
(Optional-Effect Injection doctrine case 16).

Confidence scale per L2 spec §4.3 — catalog-diff signal is structural
and unambiguous (a table_id is either in the set or not), so
confidence is high. Tunable via constructor knobs.

Reuse posture — L2 introduces ONE NEW lightweight Reader Protocol
(:class:`CatalogSnapshotReader`, see :mod:`.protocol` for the doctrine
clarification — it reads catalog-mirror substrate, not a peer L-axis
projection). The Reader is consumed by the L2 reactivity's gather_fn,
NOT by the strategies themselves; strategies operate on
already-reconstructed :class:`CatalogSnapshot` records passed in via
``propose(current=..., baseline=...)``.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .protocol import (
    CatalogDriftStrategy,
    CatalogSnapshot,
    ProposedCatalogDrift,
    make_drift_id,
)

__all__ = [
    "ColumnSetDriftStrategy",
    "ColumnTypeDriftStrategy",
    "TableSetDriftStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_drift(
    *,
    source_id: str,
    table_id: str,
    column: str | None,
    drift_kind: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    strategy: str,
    confidence: float,
    reasoning: str,
    evidence: dict[str, Any],
) -> ProposedCatalogDrift:
    """Construct a :class:`ProposedCatalogDrift` with canonical
    ``drift_id``.

    Single shared constructor across strategies — guarantees the
    ``drift_id`` hash is computed consistently via
    :func:`make_drift_id`. Confidence is clamped to [0.0, 1.0]
    and rounded to 4 places for ledger-write byte-stability.
    """
    return ProposedCatalogDrift(
        drift_id=make_drift_id(
            source_id=source_id,
            table_id=table_id,
            column=column,
            drift_kind=drift_kind,
            before=before,
            after=after,
        ),
        source_id=source_id,
        table_id=table_id,
        column=column,
        drift_kind=drift_kind,
        before=before,
        after=after,
        strategy=strategy,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        reasoning=reasoning,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — TableSetDriftStrategy
# ---------------------------------------------------------------------------


class TableSetDriftStrategy:
    """Table-set drift detection — productive day-1.

    Diffs the table-id set of ``current`` vs ``baseline``:

      * Each ``table_id`` in ``current`` but not ``baseline`` →
        emit ``drift_kind="table_added"``, ``before=None``,
        ``after={"table_id": ...}``.
      * Each ``table_id`` in ``baseline`` but not ``current`` →
        emit ``drift_kind="table_removed"``, ``before={"table_id": ...}``,
        ``after=None``.

    When ``baseline`` is ``None`` (first snapshot for the source),
    returns ``[]`` — the first snapshot is the baseline, not a drift.

    When the two snapshots have identical table_id sets, returns
    ``[]`` (no proposals).

    **Productive day-1** per Sub-wave A verification:
    ``external_catalog_imported`` payload carries ``added_table_ids``
    / ``removed_table_ids`` tuples; this strategy computes the same
    diff fresh from the reconstructed snapshots (so it does not
    depend on the catalog-mirror's pre-computed diff fields — it
    is the canonical L2 source of truth for table-set drifts).

    Confidence: 0.90 (high — set membership is unambiguous).

    name: str = ``"table_set"``
    """

    name: str = "table_set"

    DEFAULT_CONFIDENCE: float = 0.90

    def __init__(
        self,
        *,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.confidence = confidence

    async def propose(
        self,
        *,
        company_id: UUID,
        current: CatalogSnapshot,
        baseline: CatalogSnapshot | None,
    ) -> list[ProposedCatalogDrift]:
        """Diff current vs baseline; emit one proposal per added/removed table."""
        del company_id  # snapshot pair is already tenant-scoped by the gather_fn.
        if baseline is None:
            # First snapshot — no drift to report.
            return []

        current_tables: dict[str, str] = {t.table_id: t.table_id for t in current.tables}
        baseline_tables: dict[str, str] = {t.table_id: t.table_id for t in baseline.tables}

        added = sorted(set(current_tables) - set(baseline_tables))
        removed = sorted(set(baseline_tables) - set(current_tables))

        proposals: list[ProposedCatalogDrift] = []
        for table_id in added:
            after_descriptor: dict[str, Any] = {"table_id": table_id}
            proposals.append(_build_drift(
                source_id=current.source_id,
                table_id=table_id,
                column=None,
                drift_kind="table_added",
                before=None,
                after=after_descriptor,
                strategy=self.name,
                confidence=self.confidence,
                reasoning=(
                    f"table_id {table_id!r} present in current snapshot "
                    f"(as_of={current.as_of.isoformat()}) but absent from "
                    f"baseline (as_of={baseline.as_of.isoformat()}); "
                    f"propose table_added at {self.confidence:.2f}"
                ),
                evidence={
                    "heuristic": "table_set_diff",
                    "added_table_id": table_id,
                    "current_as_of": current.as_of.isoformat(),
                    "baseline_as_of": baseline.as_of.isoformat(),
                },
            ))
        for table_id in removed:
            before_descriptor: dict[str, Any] = {"table_id": table_id}
            proposals.append(_build_drift(
                source_id=current.source_id,
                table_id=table_id,
                column=None,
                drift_kind="table_removed",
                before=before_descriptor,
                after=None,
                strategy=self.name,
                confidence=self.confidence,
                reasoning=(
                    f"table_id {table_id!r} present in baseline snapshot "
                    f"(as_of={baseline.as_of.isoformat()}) but absent from "
                    f"current (as_of={current.as_of.isoformat()}); "
                    f"propose table_removed at {self.confidence:.2f}"
                ),
                evidence={
                    "heuristic": "table_set_diff",
                    "removed_table_id": table_id,
                    "current_as_of": current.as_of.isoformat(),
                    "baseline_as_of": baseline.as_of.isoformat(),
                },
            ))
        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — ColumnSetDriftStrategy
# ---------------------------------------------------------------------------


class ColumnSetDriftStrategy:
    """Per-table column-set drift detection — configured · empty-upstream today.

    For each table_id present in BOTH ``current`` and ``baseline``:

      * Each column ``name`` in ``current`` but not ``baseline`` →
        emit ``drift_kind="column_added"``, ``before=None``,
        ``after={"name": ...}``.
      * Each column ``name`` in ``baseline`` but not ``current`` →
        emit ``drift_kind="column_removed"``, ``before={"name": ...}``,
        ``after=None``.

    Tables only-in-current / only-in-baseline are handled by
    :class:`TableSetDriftStrategy` — this strategy does NOT emit
    column-level drifts for tables that were entirely added or
    removed.

    **Honest empty-upstream stub today** per Sub-wave A handoff
    concern: the ``external_catalog_imported`` payload carries no
    per-column structure (``CatalogTable.columns == ()`` for every
    table reconstructed by today's :class:`CatalogSnapshotReader`).
    When BOTH snapshots' tables have ``columns == ()``, the strategy
    returns ``[]`` immediately with no work performed — this is the
    "configured · empty-upstream" posture per spec §4.3.

    **Productive once richer emitters land**: same code path emits
    proposals automatically without any L2-side schema change.

    Confidence: 0.85 (slightly lower than TableSet because column-set
    diffs are sometimes a rename pair that should ideally collapse
    to ``column_type_changed`` — a future strategy could merge
    matching add/remove pairs into renames).

    name: str = ``"column_set"``
    """

    name: str = "column_set"

    DEFAULT_CONFIDENCE: float = 0.85

    def __init__(
        self,
        *,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.confidence = confidence

    async def propose(
        self,
        *,
        company_id: UUID,
        current: CatalogSnapshot,
        baseline: CatalogSnapshot | None,
    ) -> list[ProposedCatalogDrift]:
        """Per-table column-set diff; honest stub when columns are empty."""
        del company_id
        if baseline is None:
            return []

        # Empty-upstream short-circuit: when neither snapshot has any
        # column structure on any table, we cannot diff columns. The
        # honest stub posture per spec §4.3 — no proposals, no work.
        any_columns_in_current = any(t.columns for t in current.tables)
        any_columns_in_baseline = any(t.columns for t in baseline.tables)
        if not any_columns_in_current and not any_columns_in_baseline:
            return []

        baseline_tables_by_id: dict[str, tuple[Any, ...]] = {
            t.table_id: t.columns for t in baseline.tables
        }

        proposals: list[ProposedCatalogDrift] = []
        for cur_table in current.tables:
            base_cols_tuple = baseline_tables_by_id.get(cur_table.table_id)
            if base_cols_tuple is None:
                # Table is only in current — TableSet strategy handles it.
                continue
            current_col_names = {c.name for c in cur_table.columns}
            baseline_col_names = {c.name for c in base_cols_tuple}
            added = sorted(current_col_names - baseline_col_names)
            removed = sorted(baseline_col_names - current_col_names)
            for col_name in added:
                proposals.append(_build_drift(
                    source_id=current.source_id,
                    table_id=cur_table.table_id,
                    column=col_name,
                    drift_kind="column_added",
                    before=None,
                    after={"name": col_name},
                    strategy=self.name,
                    confidence=self.confidence,
                    reasoning=(
                        f"column {col_name!r} present on "
                        f"{cur_table.table_id!r} in current snapshot but "
                        f"absent from baseline; propose column_added at "
                        f"{self.confidence:.2f}"
                    ),
                    evidence={
                        "heuristic": "column_set_diff",
                        "added_column_name": col_name,
                        "table_id": cur_table.table_id,
                        "current_as_of": current.as_of.isoformat(),
                        "baseline_as_of": baseline.as_of.isoformat(),
                    },
                ))
            for col_name in removed:
                proposals.append(_build_drift(
                    source_id=current.source_id,
                    table_id=cur_table.table_id,
                    column=col_name,
                    drift_kind="column_removed",
                    before={"name": col_name},
                    after=None,
                    strategy=self.name,
                    confidence=self.confidence,
                    reasoning=(
                        f"column {col_name!r} present on "
                        f"{cur_table.table_id!r} in baseline snapshot but "
                        f"absent from current; propose column_removed at "
                        f"{self.confidence:.2f}"
                    ),
                    evidence={
                        "heuristic": "column_set_diff",
                        "removed_column_name": col_name,
                        "table_id": cur_table.table_id,
                        "current_as_of": current.as_of.isoformat(),
                        "baseline_as_of": baseline.as_of.isoformat(),
                    },
                ))
        return proposals


# ---------------------------------------------------------------------------
# Strategy 3 — ColumnTypeDriftStrategy
# ---------------------------------------------------------------------------


class ColumnTypeDriftStrategy:
    """Per-column type drift detection — configured · empty-upstream today.

    For each ``(table_id, column.name)`` present in BOTH ``current``
    and ``baseline``:

      * When ``current.type != baseline.type`` (both non-None) →
        emit ``drift_kind="column_type_changed"``,
        ``before={"type": baseline_type}``,
        ``after={"type": current_type}``.

    Same-name same-type → no proposal. One side ``type is None`` →
    no proposal (insufficient signal to assert a change vs the
    other side; the payload validator on ``column_type_changed``
    requires BOTH sides non-None on the ``before``/``after`` dicts).

    **Honest empty-upstream stub today** per Sub-wave A handoff
    concern: ``CatalogTable.columns == ()`` for every table
    reconstructed by today's :class:`CatalogSnapshotReader`, so the
    strategy returns ``[]`` immediately. **Productive once richer
    emitters land** with per-column type metadata.

    Confidence: 0.80 (slightly lower than ColumnSet because type
    inference upstream can be noisy — a ``varchar`` vs
    ``varchar(255)`` rendering difference is structural drift
    even though the semantic type is unchanged).

    name: str = ``"column_type"``
    """

    name: str = "column_type"

    DEFAULT_CONFIDENCE: float = 0.80

    def __init__(
        self,
        *,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.confidence = confidence

    async def propose(
        self,
        *,
        company_id: UUID,
        current: CatalogSnapshot,
        baseline: CatalogSnapshot | None,
    ) -> list[ProposedCatalogDrift]:
        """Per-column type diff; honest stub when type metadata is missing."""
        del company_id
        if baseline is None:
            return []

        # Empty-upstream short-circuit — same posture as ColumnSet.
        any_columns_in_current = any(t.columns for t in current.tables)
        any_columns_in_baseline = any(t.columns for t in baseline.tables)
        if not any_columns_in_current and not any_columns_in_baseline:
            return []

        baseline_tables_by_id: dict[str, dict[str, str | None]] = {}
        for t in baseline.tables:
            baseline_tables_by_id[t.table_id] = {
                c.name: c.type for c in t.columns
            }

        proposals: list[ProposedCatalogDrift] = []
        for cur_table in current.tables:
            base_col_types = baseline_tables_by_id.get(cur_table.table_id)
            if base_col_types is None:
                continue
            for cur_col in cur_table.columns:
                baseline_type = base_col_types.get(cur_col.name)
                # Skip rows where column isn't in baseline (handled by
                # ColumnSet) or where either side lacks type info.
                if baseline_type is None or cur_col.type is None:
                    continue
                if baseline_type == cur_col.type:
                    continue
                proposals.append(_build_drift(
                    source_id=current.source_id,
                    table_id=cur_table.table_id,
                    column=cur_col.name,
                    drift_kind="column_type_changed",
                    before={"type": baseline_type},
                    after={"type": cur_col.type},
                    strategy=self.name,
                    confidence=self.confidence,
                    reasoning=(
                        f"column {cur_col.name!r} on "
                        f"{cur_table.table_id!r} changed type from "
                        f"{baseline_type!r} to {cur_col.type!r}; "
                        f"propose column_type_changed at "
                        f"{self.confidence:.2f}"
                    ),
                    evidence={
                        "heuristic": "column_type_diff",
                        "table_id": cur_table.table_id,
                        "column_name": cur_col.name,
                        "before_type": baseline_type,
                        "after_type": cur_col.type,
                        "current_as_of": current.as_of.isoformat(),
                        "baseline_as_of": baseline.as_of.isoformat(),
                    },
                ))
        return proposals


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[CatalogDriftStrategy], ...] = (
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    TableSetDriftStrategy,
)
del _proto_check
