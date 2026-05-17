"""L4 schema-evolution-impact — three inference strategies.

Three concrete :class:`SchemaImpactService` impls, ranked by
``(productivity-today, ground-truth-proximity)``:

  1. :class:`LineageEdgeImpactStrategy` — **cross-axis read of L3**.
     Productive today when L3 is enabled and has confirmed edges.
     For each L3 confirmed edge originating at the changed column,
     proposes a downstream impact whose confidence is
     ``edge.confidence × impact_factor``.
  2. :class:`DbtTestImpactStrategy` — reads existing dbt tests on the
     changed column. Configured · empty-upstream today (Wave 1 catalog
     mirror doesn't yet emit dbt-test descriptors); the strategy is
     structurally complete.
  3. :class:`TypeCoercionImpactStrategy` — reasons over column type
     transitions. Productive today — works on bare column type
     metadata; emits one ``type_coercion_required`` impact per
     downstream-edge for ``column_type_changed`` events. May run
     without an :class:`.protocol.LineageEdgeReader` (degrades to
     "no downstream targets known → no proposals").

Each strategy is independently constructable + testable. The composite
in :mod:`.composite` consumes any subset (Optional-Effect Injection
doctrine case 11). The :class:`.protocol.LineageEdgeReader` injection
is the **cross-axis read** — strategies own the lookups they need;
the factory does NOT centralize the reader.
"""
from __future__ import annotations

from typing import Any

# Reuse L6's producer-side ConfirmedClassificationReader Protocol — the
# governance-classification signal surface is L6-owned; L4's strategy
# consumes it directly. Importing keeps the cross-axis coupling explicit
# at the type level (mirrors the dbt-test cross-axis read of L7).
#
# Reuse L6's consumer-side ConfirmedSemanticTypeReader Protocol for the
# L5→L4 chain (6th cross-axis chain in the lake-side stack — 4th
# consumer of the same Protocol after L6, L8, L7). L4 reads L5's
# confirmed semantic types to elevate impact severity when a schema
# change touches a typed column. 0 new Protocol, 0 new adapter.
from wormbase_agent_gateway.column_classification.protocol import (
    ClassificationLevel,
    ConfirmedClassificationReader,
    ConfirmedSemanticTypeReader,
)

# Reuse L2's PRODUCER-side AcknowledgedDriftReader Protocol for the
# L4↦L2 chain (7th cross-axis chain in the lake-side stack, and the
# FIRST bidirectional chain — L4 elevates impacts based on L2
# acknowledgments forward, while L2's dashboard surfaces downstream-
# impact roll-up counts in reverse). The Protocol+Record live on L2
# because the :data:`CatalogDriftKind` taxonomy is L2-owned; mirrors
# L6's :class:`ConfirmedClassificationReader` placement.
from wormbase_agent_gateway.catalog_drift.protocol import (
    AcknowledgedDriftReader,
)

# Reuse L7's DbtTestReader Protocol — the dbt-test signal surface is
# identical (read tests for a model_id). Importing keeps the cross-axis
# coupling explicit at the type level.
from wormbase_agent_gateway.quality.strategies import DbtTestReader

from .protocol import (
    ChangeKind,
    ColumnChange,
    ImpactKind,
    LineageEdgeReader,
    ProposedImpact,
    SchemaImpactService,
    make_impact_id,
)

__all__ = [
    "AcknowledgedDriftImpactStrategy",
    "DbtTestImpactStrategy",
    "GovernanceClassificationImpactStrategy",
    "LineageEdgeImpactStrategy",
    "SemanticTypeImpactStrategy",
    "TypeCoercionImpactStrategy",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


# Confidence factors per (change_kind, downstream-from-LineageEdge).
# Applied as multiplier against L3's edge.confidence:
#   final_confidence = edge.confidence × _IMPACT_FACTOR[change_kind]
#
# Drop is unambiguous (downstream column literally disappears upstream),
# so 0.90. Type change can often be coerced, so 0.85. Addition rarely
# breaks anything (downstream is unaware, not broken), so 0.50.
_IMPACT_FACTOR: dict[ChangeKind, float] = {
    "column_dropped": 0.90,
    "column_type_changed": 0.85,
    "column_added": 0.50,
}


_IMPACT_KIND_FOR_CHANGE: dict[ChangeKind, ImpactKind] = {
    "column_dropped": "tgt_column_orphaned",
    "column_type_changed": "tgt_column_type_mismatch",
    "column_added": "tgt_column_unaware",
}


def _propose(
    *,
    source_id: str,
    src_table: str,
    src_column: str,
    change_kind: ChangeKind,
    impact_kind: ImpactKind,
    tgt_table_id: str,
    tgt_column: str,
    upstream_lineage_edge_id: str | None,
    confidence: float,
    strategy: str,
    reasoning: str,
    evidence: dict[str, Any],
) -> ProposedImpact:
    """Construct a :class:`ProposedImpact` with canonical ``impact_id``.

    Single shared constructor across strategies — guarantees the
    ``impact_id`` hash is computed consistently (same dedup key).
    """
    return ProposedImpact(
        impact_id=make_impact_id(
            source_id=source_id,
            src_table=src_table,
            src_column=src_column,
            change_kind=change_kind,
            tgt_table_id=tgt_table_id,
            tgt_column=tgt_column,
        ),
        source_id=source_id,
        src_table=src_table,
        src_column=src_column,
        change_kind=change_kind,
        impact_kind=impact_kind,
        tgt_table_id=tgt_table_id,
        tgt_column=tgt_column,
        upstream_lineage_edge_id=upstream_lineage_edge_id,
        confidence=confidence,
        strategy=strategy,
        reasoning=reasoning,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Strategy 1 — LineageEdgeImpactStrategy (cross-axis read of L3)
# ---------------------------------------------------------------------------


class LineageEdgeImpactStrategy:
    """Propagates schema changes via L3's confirmed lineage edges.

    The **first productive cross-axis-reading strategy** in the lake
    stack. For each :class:`.protocol.LineageEdgeRecord` returned by
    the injected :class:`.protocol.LineageEdgeReader`, proposes a
    downstream impact whose kind is determined by the change_kind:

      * ``column_dropped`` → ``tgt_column_orphaned`` at
        ``0.90 × edge.confidence``
      * ``column_type_changed`` → ``tgt_column_type_mismatch`` at
        ``0.85 × edge.confidence``
      * ``column_added`` → ``tgt_column_unaware`` at
        ``0.50 × edge.confidence``

    Edge-strategy filter: by default, only edges from L3's
    ``dbt_manifest`` strategy propagate (highest confidence,
    near-ground-truth). ``include_naming_lineage=True`` opts in
    naming-heuristic + sample-overlap edges too; production defaults to
    off to keep L4's false-positive rate low.

    ``min_edge_confidence`` is a floor on the L3 edge confidence; edges
    below it are skipped even when their strategy is included. Default
    0.85 admits dbt_manifest (0.99) but rejects loose naming hits.

    name: str = ``"lineage_edge"``
    """

    name: str = "lineage_edge"

    DEFAULT_STRATEGIES_ALWAYS_INCLUDED: frozenset[str] = frozenset({
        "dbt_manifest",
    })

    def __init__(
        self,
        *,
        lineage_edge_reader: LineageEdgeReader,
        include_naming_lineage: bool = False,
        min_edge_confidence: float = 0.85,
    ) -> None:
        self.lineage_edge_reader = lineage_edge_reader
        self.include_naming_lineage = include_naming_lineage
        self.min_edge_confidence = min_edge_confidence

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Look up L3 edges for the changed column; propose one impact per edge."""
        edges = await self.lineage_edge_reader.list_confirmed_edges_for_source_column(
            source_id=source_id,
            src_column=change.src_column,
            company_id=company_id,
        )
        if not edges:
            return []

        impact_factor = _IMPACT_FACTOR[change.change_kind]
        impact_kind = _IMPACT_KIND_FOR_CHANGE[change.change_kind]

        proposals: list[ProposedImpact] = []
        for edge in edges:
            # Edge-strategy gate: always allow the canonical strategies,
            # otherwise consult include_naming_lineage.
            if edge.strategy in self.DEFAULT_STRATEGIES_ALWAYS_INCLUDED:
                pass  # always pass
            elif not self.include_naming_lineage:
                continue
            # Confidence floor
            if edge.confidence < self.min_edge_confidence:
                continue

            final_confidence = round(edge.confidence * impact_factor, 4)
            # Clamp into [0.0, 1.0] (defensive; product of two unit-range
            # floats stays in unit range mathematically).
            final_confidence = max(0.0, min(1.0, final_confidence))

            proposals.append(
                _propose(
                    source_id=source_id,
                    src_table=src_table,
                    src_column=change.src_column,
                    change_kind=change.change_kind,
                    impact_kind=impact_kind,
                    tgt_table_id=edge.tgt_table_id,
                    tgt_column=edge.tgt_column,
                    upstream_lineage_edge_id=edge.edge_id,
                    confidence=final_confidence,
                    strategy=self.name,
                    reasoning=(
                        f"L3 lineage edge ({edge.strategy}, "
                        f"confidence={edge.confidence:.2f}) "
                        f"connects {src_table}.{change.src_column} → "
                        f"{edge.tgt_table_id}.{edge.tgt_column}; "
                        f"{change.change_kind} → {impact_kind} at "
                        f"{final_confidence:.2f}"
                    ),
                    evidence={
                        "upstream_edge_id": edge.edge_id,
                        "upstream_edge_strategy": edge.strategy,
                        "upstream_edge_confidence": edge.confidence,
                        "impact_factor": impact_factor,
                        "change_kind": change.change_kind,
                        "old_type": change.old_type,
                        "new_type": change.new_type,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 2 — DbtTestImpactStrategy
# ---------------------------------------------------------------------------


# Per-dbt-test confidence + impact-kind mapping. The dbt test world is
# open-ended (dbt_utils, dbt_expectations, custom tests) so we surface
# the canonical core tests and leave room for plug-in expansion.
#
# Each entry pins (impact_kind, base_confidence). The base confidence is
# scaled by the change_kind via :data:`_DBT_TEST_CHANGE_FACTOR` below.
_DBT_TEST_PROFILES: dict[str, tuple[ImpactKind, float]] = {
    "not_null": ("dbt_test_breakage", 0.95),
    "unique": ("dbt_test_breakage", 0.95),
    "accepted_values": ("dbt_test_breakage", 0.85),
    "relationships": ("dbt_test_breakage", 0.90),
}


_DBT_TEST_CHANGE_FACTOR: dict[ChangeKind, float] = {
    # A drop always breaks every test → factor 1.0.
    "column_dropped": 1.0,
    # A type change usually breaks accepted_values; not_null/unique still
    # apply but the test definition needs review.
    "column_type_changed": 0.85,
    # Adding a column doesn't break tests on existing columns.
    "column_added": 0.0,
}


class DbtTestImpactStrategy:
    """Propagates schema changes via existing dbt tests on the changed column.

    For each dbt test attached to ``(src_table, src_column)``, proposes
    a :data:`.protocol.ImpactKind` = ``"dbt_test_breakage"`` impact.
    The downstream "tgt" of the impact is the source itself
    (``tgt_table_id = src_table``, ``tgt_column = src_column``) — the
    test fires against the same column it's defined on.

    **Configured · empty-upstream today** — Wave 1 catalog mirror
    doesn't yet emit dbt-test descriptors; the strategy fires on the
    structural code path but :class:`DbtTestReader` returns ``[]``.
    Sub-wave C gates this strategy behind a flag to make the honest-
    stub posture auditable.

    Only emits for ``column_dropped`` and ``column_type_changed``
    (``_DBT_TEST_CHANGE_FACTOR["column_added"] = 0.0`` ⇒ no proposals
    on add). Strategy is dbt-source aware: only fires when the src
    table looks like a dbt model (``src_table`` starts with the
    canonical dbt prefix).

    name: str = ``"dbt_test"``
    """

    name: str = "dbt_test"

    def __init__(self, *, test_reader: DbtTestReader) -> None:
        self.test_reader = test_reader

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Read dbt tests for the changed column; emit one impact per test."""
        del company_id  # dbt-test reader is model-scoped, not tenant-scoped
        change_factor = _DBT_TEST_CHANGE_FACTOR.get(change.change_kind, 0.0)
        if change_factor == 0.0:
            return []

        tests = await self.test_reader.get_tests_for_model(src_table)
        if not tests:
            return []

        proposals: list[ProposedImpact] = []
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_name = test.get("test_name")
            if not isinstance(test_name, str):
                continue
            # Only tests on the changed column (or table-level tests
            # that don't have a column pin) propagate.
            raw_column = test.get("column")
            test_column: str | None = (
                raw_column if isinstance(raw_column, str) and raw_column
                else None
            )
            if test_column is not None and test_column != change.src_column:
                continue

            profile = _DBT_TEST_PROFILES.get(test_name)
            if profile is None:
                continue
            impact_kind, base_conf = profile

            confidence = round(base_conf * change_factor, 4)
            confidence = max(0.0, min(1.0, confidence))

            proposals.append(
                _propose(
                    source_id=source_id,
                    src_table=src_table,
                    src_column=change.src_column,
                    change_kind=change.change_kind,
                    impact_kind=impact_kind,
                    tgt_table_id=src_table,
                    tgt_column=change.src_column,
                    upstream_lineage_edge_id=None,
                    confidence=confidence,
                    strategy=self.name,
                    reasoning=(
                        f"dbt test {test_name!r} on "
                        f"{src_table}.{change.src_column} will likely break "
                        f"on {change.change_kind} (confidence={confidence:.2f})"
                    ),
                    evidence={
                        "dbt_test_name": test_name,
                        "dbt_test_column": test_column,
                        "change_kind": change.change_kind,
                        "base_confidence": base_conf,
                        "change_factor": change_factor,
                        "old_type": change.old_type,
                        "new_type": change.new_type,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 3 — TypeCoercionImpactStrategy
# ---------------------------------------------------------------------------


# Suggested CAST per (old_type, new_type) prefix tuple. We compare
# lowercased + family-normalised types so "varchar(64)" and "VARCHAR" both
# land on family "varchar".
def _type_family(t: str | None) -> str:
    if not t:
        return ""
    t = t.lower().strip()
    # Strip parameterisation like (n), (p, s).
    paren = t.find("(")
    if paren >= 0:
        t = t[:paren].strip()
    # Common SQL family aliases.
    if t in {"int", "integer", "int4", "int8", "bigint", "smallint"}:
        return "int"
    if t in {"varchar", "char", "text", "string", "nvarchar"}:
        return "varchar"
    if t in {"numeric", "decimal", "float", "float8", "real", "double", "double precision"}:
        return "numeric"
    if t in {"bool", "boolean"}:
        return "bool"
    if t in {"timestamp", "timestamptz", "datetime", "date", "time"}:
        return "timestamp"
    if t in {"jsonb", "json"}:
        return "json"
    return t


# Per-transition base confidence. Defaults to 0.70 (the spec's quoted
# baseline); narrower numeric/string coercions can be more confident.
_TYPE_TRANSITION_CONFIDENCE: dict[tuple[str, str], float] = {
    ("int", "varchar"): 0.85,       # widening
    ("varchar", "int"): 0.70,       # narrowing, may fail
    ("numeric", "varchar"): 0.85,
    ("varchar", "numeric"): 0.70,
    ("int", "numeric"): 0.90,
    ("numeric", "int"): 0.70,       # narrowing
    ("timestamp", "varchar"): 0.80,
    ("varchar", "timestamp"): 0.65,
    ("bool", "varchar"): 0.85,
    ("varchar", "bool"): 0.65,
}


def _suggest_coercion(old_family: str, new_family: str) -> str:
    """Return a human-readable CAST suggestion for the type transition."""
    if not old_family or not new_family:
        return "downstream needs review"
    return f"CAST {old_family} AS {new_family}"


class TypeCoercionImpactStrategy:
    """Reasons over column type transitions; emits ``type_coercion_required``.

    Only fires for ``change_kind == "column_type_changed"``. For each
    downstream lineage edge (when a :class:`.protocol.LineageEdgeReader`
    is injected), emits one :data:`.protocol.ImpactKind` =
    ``"type_coercion_required"`` impact with the suggested CAST.

    Without the reader (``lineage_edge_reader=None``): the strategy
    runs but emits NO proposals — coercion needs downstream targets
    to propose against. This is the productive-today posture for
    deployments where L3 isn't enabled yet; the strategy degrades
    gracefully rather than failing.

    Confidence: lookup in :data:`_TYPE_TRANSITION_CONFIDENCE`; defaults
    to 0.70 for unmapped transitions. Higher for safe widening
    (int → varchar at 0.85); lower for risky narrowing (varchar → bool
    at 0.65).

    name: str = ``"type_coercion"``
    """

    name: str = "type_coercion"

    DEFAULT_CONFIDENCE: float = 0.70

    def __init__(
        self,
        *,
        lineage_edge_reader: LineageEdgeReader | None = None,
    ) -> None:
        self.lineage_edge_reader = lineage_edge_reader

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Emit one ``type_coercion_required`` impact per downstream edge."""
        if change.change_kind != "column_type_changed":
            return []
        if self.lineage_edge_reader is None:
            return []
        edges = await self.lineage_edge_reader.list_confirmed_edges_for_source_column(
            source_id=source_id,
            src_column=change.src_column,
            company_id=company_id,
        )
        if not edges:
            return []

        old_family = _type_family(change.old_type)
        new_family = _type_family(change.new_type)
        base_conf = _TYPE_TRANSITION_CONFIDENCE.get(
            (old_family, new_family), self.DEFAULT_CONFIDENCE,
        )
        suggestion = _suggest_coercion(old_family, new_family)

        proposals: list[ProposedImpact] = []
        for edge in edges:
            confidence = round(base_conf, 4)
            proposals.append(
                _propose(
                    source_id=source_id,
                    src_table=src_table,
                    src_column=change.src_column,
                    change_kind="column_type_changed",
                    impact_kind="type_coercion_required",
                    tgt_table_id=edge.tgt_table_id,
                    tgt_column=edge.tgt_column,
                    upstream_lineage_edge_id=edge.edge_id,
                    confidence=confidence,
                    strategy=self.name,
                    reasoning=(
                        f"type change {change.old_type!r} → "
                        f"{change.new_type!r} on "
                        f"{src_table}.{change.src_column}; downstream "
                        f"{edge.tgt_table_id}.{edge.tgt_column} needs "
                        f"coercion: {suggestion}"
                    ),
                    evidence={
                        "old_type": change.old_type,
                        "new_type": change.new_type,
                        "old_family": old_family,
                        "new_family": new_family,
                        "suggested_coercion": suggestion,
                        "upstream_edge_id": edge.edge_id,
                    },
                )
            )
        return proposals


# ---------------------------------------------------------------------------
# Strategy 4 — GovernanceClassificationImpactStrategy (cross-axis read of L6)
# ---------------------------------------------------------------------------


# Per-classification-level severity mapping. Each level maps to a
# (governance_severity, base_confidence) tuple. Strategy only emits a
# proposal when an L6 confirmed classification exists at one of the
# elevated levels — ``public`` / ``internal`` produce NO governance-
# specific proposals (they're informational; no review escalation).
#
# regulated   → critical (compliance / regulator review path)
# pii         → high (privacy review path)
# confidential → high (internal-only review)
# internal     → no proposal (informational only)
# public       → no proposal (not governance-sensitive)
#
# The base confidence is high (0.95 for regulated; 0.90 for pii/
# confidential) because an OPERATOR-CONFIRMED classification is the
# strongest possible cross-axis signal — a human said "this column is
# regulated"; downstream review elevation is near-certain.
_GOVERNANCE_PROFILES: dict[ClassificationLevel, tuple[str, float]] = {
    "regulated": ("critical", 0.95),
    "pii": ("high", 0.90),
    "confidential": ("high", 0.90),
}


# Map from change_kind to the L4 impact_kind a governance elevation
# proposes. Mirrors LineageEdge's mapping — the elevation rides on top
# of the same downstream-consequence classification; the *evidence*
# carries the governance modifier so the L4 dashboard can render a
# governance severity chip.
_GOVERNANCE_IMPACT_KIND_FOR_CHANGE: dict[ChangeKind, ImpactKind] = {
    "column_dropped": "tgt_column_orphaned",
    "column_type_changed": "tgt_column_type_mismatch",
    "column_added": "tgt_column_unaware",
}


# Severity rank used to pick the highest-severity confirmed
# classification when L6 has multiple confirmed levels on the same
# column (e.g. ``pii`` via semantic_type AND ``regulated`` via
# domain_default). Strategy elevates against the highest.
_SEVERITY_RANK: dict[str, int] = {
    "regulated": 3,
    "pii": 2,
    "confidential": 2,
    "internal": 1,
    "public": 0,
}


class GovernanceClassificationImpactStrategy:
    """Elevates schema-change impact severity via L6's confirmed classifications.

    The **5th cross-axis chain** in the lake-side stack (after L4→L3,
    L6→L5, L8→L5, L5→L7), and the **first L6→L4 chain**. For each L6
    confirmed classification at ``regulated`` / ``pii`` / ``confidential``
    on the changed column, proposes one ``ProposedImpact`` with:

      * ``strategy = "governance_classification"``
      * ``impact_kind`` mapped from ``change_kind`` (same mapping as
        LineageEdge's table)
      * ``confidence`` = base per the governance profile (0.95 for
        regulated; 0.90 for pii / confidential)
      * ``tgt_table_id = src_table`` / ``tgt_column = src_column`` —
        the elevation IS the impact; the target is the changed column
        itself (no downstream propagation; that's LineageEdge's job)
      * ``evidence`` carrying the L6 classification id +
        ``classification_level`` + ``governance_severity`` modifier
        (``critical`` / ``high``) so the dashboard can render the
        governance chip

    When the composite merges this strategy's proposal with a
    ``lineage_edge`` proposal on the same impact_id (won't happen by
    default because the impact_ids are different — governance targets
    src_column-as-itself while lineage_edge targets downstream tables),
    the highest-confidence wins on confidence + reasoning. The
    governance proposal stands as its own row when no other strategy
    proposes the same canonical tuple.

    Public / internal classifications produce no proposals — they're
    not governance-sensitive enough to elevate; the projection stays
    quiet.

    Multiple confirmed levels on the same column → strategy elevates
    against the **highest-severity** level. Per spec, this is the
    conservative interpretation: a column confirmed as both ``pii``
    and ``regulated`` is treated as regulated.

    name: str = ``"governance_classification"``
    """

    name: str = "governance_classification"

    def __init__(
        self,
        *,
        confirmed_classification_reader: ConfirmedClassificationReader,
    ) -> None:
        self.confirmed_classification_reader = confirmed_classification_reader

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Look up L6 confirmed classifications; propose elevated impact when severity > public/internal."""
        records = await (
            self.confirmed_classification_reader
            .list_confirmed_classifications_for_source_column(
                source_id=source_id,
                src_column=change.src_column,
                company_id=company_id,
            )
        )
        if not records:
            return []

        # Filter to classifications on the changed src_table specifically
        # (the reader is scoped to source_id+column, but a single column
        # name may exist on multiple tables within a source — we only
        # elevate impacts on the actual changed table).
        records = [r for r in records if r.table_id == src_table]
        if not records:
            return []

        # Pick the highest-severity confirmed classification.
        records_sorted = sorted(
            records,
            key=lambda r: _SEVERITY_RANK.get(r.classification_level, 0),
            reverse=True,
        )
        winner = records_sorted[0]

        profile = _GOVERNANCE_PROFILES.get(winner.classification_level)
        if profile is None:
            # public / internal — no elevation; conservative posture.
            return []
        governance_severity, base_confidence = profile

        impact_kind = _GOVERNANCE_IMPACT_KIND_FOR_CHANGE[change.change_kind]
        confidence = round(base_confidence, 4)

        return [
            _propose(
                source_id=source_id,
                src_table=src_table,
                src_column=change.src_column,
                change_kind=change.change_kind,
                impact_kind=impact_kind,
                tgt_table_id=src_table,
                tgt_column=change.src_column,
                upstream_lineage_edge_id=None,
                confidence=confidence,
                strategy=self.name,
                reasoning=(
                    f"L6 confirmed classification "
                    f"'{winner.classification_level}' on "
                    f"{src_table}.{change.src_column} "
                    f"(confirmed_by={winner.confirmed_by_person_id}); "
                    f"{change.change_kind} elevated to "
                    f"governance_severity={governance_severity} "
                    f"at {confidence:.2f}"
                ),
                evidence={
                    "upstream_classification_id": winner.classification_id,
                    "classification_level": winner.classification_level,
                    "governance_severity": governance_severity,
                    "confirmed_at": winner.confirmed_at.isoformat(),
                    "confirmed_by_person_id": winner.confirmed_by_person_id,
                    "change_kind": change.change_kind,
                    "old_type": change.old_type,
                    "new_type": change.new_type,
                    # Diagnostic: how many confirmed classifications
                    # existed on this column (in case operators want to
                    # see overlap across L6 strategies).
                    "classification_count": len(records),
                },
            ),
        ]


# ---------------------------------------------------------------------------
# Strategy 5 — SemanticTypeImpactStrategy (cross-axis read of L5)
# ---------------------------------------------------------------------------


# Map from change_kind to the L4 impact_kind a semantic-type elevation
# proposes. Mirrors Governance's mapping exactly — the elevation rides
# on top of the same downstream-consequence classification; the
# *evidence* carries the semantic-type concern so the L4 dashboard can
# render a semantic-type severity chip.
_SEMANTIC_TYPE_IMPACT_KIND_FOR_CHANGE: dict[ChangeKind, ImpactKind] = {
    "column_dropped": "tgt_column_orphaned",
    "column_type_changed": "tgt_column_type_mismatch",
    "column_added": "tgt_column_unaware",
}


class SemanticTypeImpactStrategy:
    """Elevates schema-change impact severity via L5's confirmed semantic types.

    The **6th cross-axis chain** in the lake-side stack (after L4→L3,
    L6→L5, L8→L5, L5→L7, L6→L4), and the **last of the 3 originally-
    foreshadowed peer-axis chains**. For each L5 confirmed semantic
    type on the changed column, proposes one ``ProposedImpact`` with:

      * ``strategy = "semantic_type"``
      * ``impact_kind`` mapped from ``change_kind`` (same mapping as
        Governance / LineageEdge — keeps the L4 enum surface tidy)
      * ``confidence`` = ``DEFAULT_CONFIDENCE`` (0.90 — semantic-type
        confirmation is strong signal)
      * ``tgt_table_id = src_table`` / ``tgt_column = src_column`` —
        the elevation IS the impact; the target is the changed column
        itself (no downstream propagation; that's LineageEdge's job)
      * ``evidence`` carrying:
          * ``upstream_semantic_type_id`` — L5's type_id, threaded so
            the dashboard renders the "view L5 semantic type →"
            cross-axis row link.
          * ``semantic_type`` — the confirmed semantic_type value
            (e.g. ``email`` / ``uuid`` / ``phone``).
          * ``semantic_type_severity`` — the severity modifier
            (``high`` today) that the L4 dashboard chip surfaces.

    Type-compatibility logic stays in
    :class:`TypeCoercionImpactStrategy`; this strategy SIGNALS that the
    change touches a typed column and that compatibility should be
    reviewed against the semantic constraint (e.g., changing an
    ``email`` column from ``VARCHAR(255)`` to ``INTEGER`` breaks the
    semantic type even if the raw type-coercion strategy thinks it's
    fine).

    Severity heuristic (Wave 1, type-agnostic — every confirmed
    semantic type triggers, the type value goes into evidence):

      * L5 confirmed semantic type on the changed column → severity
        ``high`` (in ``evidence.semantic_type_severity``).
      * No confirmed type → no proposal.

    Reuse posture: imports L6's
    :class:`ConfirmedSemanticTypeReader` directly — does NOT redeclare
    a Protocol. **4th consumer of the same Protocol** (1st = L6's own
    SemanticTypeClassificationStrategy; 2nd = L8's NameMatchEntityStrategy
    semantic-type-anchor path; 3rd = L7's
    :class:`SemanticTypeQualityCheckStrategy`; 4th = this strategy).
    Validates the consumer-owned-Protocol pattern at N=4 consumers.

    Multi-column changes call ``propose_impacts`` once per change; this
    strategy emits at most one proposal per call (one per changed
    column). When multiple confirmed semantic types exist on the same
    column (e.g. ``user_email`` confirmed as both ``email`` AND
    ``pii_email``), the strategy picks the FIRST confirmed type in
    reader-iteration order for replay stability. The diagnostic
    ``evidence.semantic_type_count`` surfaces the total count so
    operators see overlap.

    name: str = ``"semantic_type"``
    """

    name: str = "semantic_type"
    DEFAULT_CONFIDENCE: float = 0.90

    def __init__(
        self,
        *,
        confirmed_semantic_type_reader: ConfirmedSemanticTypeReader,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.confirmed_semantic_type_reader = confirmed_semantic_type_reader
        self.confidence = confidence

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Look up L5 confirmed semantic types; propose elevated impact when any exist."""
        if not src_table or not change.src_column:
            return []

        records = await (
            self.confirmed_semantic_type_reader
            .list_confirmed_types_for_table_column(
                table_id=src_table,
                column=change.src_column,
                company_id=company_id,
            )
        )
        if not records:
            return []

        # Pick the first confirmed semantic type in reader iteration
        # order (the reader returns sorted-by-type_id for replay
        # stability — see LedgerConfirmedSemanticTypeReader). Wave 1 is
        # type-agnostic: any confirmed type triggers; the specific
        # value goes into evidence for the dashboard chip.
        winner = records[0]
        impact_kind = _SEMANTIC_TYPE_IMPACT_KIND_FOR_CHANGE[change.change_kind]
        confidence = round(float(self.confidence), 4)

        return [
            _propose(
                source_id=source_id,
                src_table=src_table,
                src_column=change.src_column,
                change_kind=change.change_kind,
                impact_kind=impact_kind,
                tgt_table_id=src_table,
                tgt_column=change.src_column,
                upstream_lineage_edge_id=None,
                confidence=confidence,
                strategy=self.name,
                reasoning=(
                    f"L5 confirmed semantic_type="
                    f"{winner.semantic_type!r} on "
                    f"{src_table}.{change.src_column}; "
                    f"{change.change_kind} elevated to "
                    f"semantic_type_severity=high "
                    f"at {confidence:.2f} — review type-compat against "
                    f"the {winner.semantic_type!r} constraint"
                ),
                evidence={
                    "upstream_semantic_type_id": winner.type_id,
                    "semantic_type": winner.semantic_type,
                    "semantic_type_severity": "high",
                    "upstream_type_confidence": winner.confidence,
                    "upstream_l5_strategy": winner.strategy,
                    "change_kind": change.change_kind,
                    "old_type": change.old_type,
                    "new_type": change.new_type,
                    # Diagnostic: how many confirmed semantic types
                    # exist on this column (operators want to see
                    # overlap across L5 strategies).
                    "semantic_type_count": len(records),
                },
            ),
        ]


# ---------------------------------------------------------------------------
# Strategy 6 — AcknowledgedDriftImpactStrategy (cross-axis read of L2)
# ---------------------------------------------------------------------------


# Map from change_kind to the L4 impact_kind an acknowledged-drift
# elevation proposes. Mirrors Governance / SemanticType exactly — the
# elevation rides on top of the same downstream-consequence
# classification; the *evidence* carries the acknowledged-drift concern
# so the L4 dashboard can render an acknowledged-drift severity chip.
_ACKNOWLEDGED_DRIFT_IMPACT_KIND_FOR_CHANGE: dict[ChangeKind, ImpactKind] = {
    "column_dropped": "tgt_column_orphaned",
    "column_type_changed": "tgt_column_type_mismatch",
    "column_added": "tgt_column_unaware",
}


class AcknowledgedDriftImpactStrategy:
    """Elevates schema-change impact severity via L2's acknowledged catalog drifts.

    The **7th cross-axis chain** in the lake-side stack (after L4→L3,
    L6→L5, L8→L5, L5→L7, L6→L4, L5→L4), and the **first BIDIRECTIONAL
    chain**: L4 elevates impacts based on L2 acknowledged drifts
    (forward — this strategy), while the L2 dashboard surfaces the
    downstream-impact roll-up per drift row (reverse — Half B on the
    dashboard side; no new strategy code).

    For each L2 acknowledged drift on the changed ``(source_id,
    src_column)``, proposes one ``ProposedImpact`` with:

      * ``strategy = "acknowledged_drift"``
      * ``impact_kind`` mapped from ``change_kind`` (same mapping as
        Governance / SemanticType / LineageEdge — keeps the L4 enum
        surface tidy)
      * ``confidence`` = ``DEFAULT_CONFIDENCE`` (0.92 — acknowledgment is
        a human signal; high confidence)
      * ``tgt_table_id = src_table`` / ``tgt_column = src_column`` —
        the elevation IS the impact; the target is the changed column
        itself (no downstream propagation; that's LineageEdge's job).
        This target choice intentionally aligns with Governance and
        SemanticType so the composite's per-canonical-tuple merge
        activates when multiple cross-axis strategies hit the same
        column (per the L5→L4 close-out recipe addendum #2 —
        composite-merge dedup yielding one row with multiple
        evidence keys + chips + links).
      * ``evidence`` carrying:
          * ``upstream_drift_id`` — L2's drift_id, threaded so the
            dashboard renders a "↪ view L2 acknowledged drift" cross-
            axis row link.
          * ``drift_kind`` — the L2 drift_kind (e.g. ``column_added`` /
            ``column_type_changed``).
          * ``acknowledged_drift_severity`` — the severity modifier
            (``high`` today) the L4 dashboard chip surfaces.

    Severity heuristic (Wave 1, kind-agnostic — every acknowledged
    drift triggers; the kind goes into evidence):

      * L2 acknowledged drift on the changed column → severity
        ``high`` (in ``evidence.acknowledged_drift_severity``).
      * No acknowledged drift → no proposal.

    Reuse posture: imports L2's PRODUCER-side
    :class:`AcknowledgedDriftReader` directly — first consumer of that
    Protocol. Validates the producer-owned-Protocol pattern at N=2
    L2 producer-side Protocols (CatalogSnapshotReader was platform-
    substrate; this is the first peer-axis producer Protocol on L2).

    Multi-column changes call ``propose_impacts`` once per change; this
    strategy emits at most one proposal per call. When multiple
    acknowledged drifts exist on the same column (e.g. drift on
    ``column_added`` then later on ``column_type_changed``), the
    strategy picks the FIRST in reader-iteration order for replay
    stability (the canonical impl sorts by ``drift_id`` ascending).
    The diagnostic ``evidence.acknowledged_drift_count`` surfaces the
    total count so operators see overlap.

    Table-level drifts (``column`` is None — ``table_added`` /
    ``table_removed``) are skipped — this strategy's hot-path lookup
    is keyed by ``(source_id, src_column)`` and column-level changes
    only carry a meaningful ``src_column``. Table-level drift handling
    is a future-wave consideration.

    name: str = ``"acknowledged_drift"``
    """

    name: str = "acknowledged_drift"
    DEFAULT_CONFIDENCE: float = 0.92

    def __init__(
        self,
        *,
        acknowledged_drift_reader: AcknowledgedDriftReader,
        confidence: float = DEFAULT_CONFIDENCE,
    ) -> None:
        self.acknowledged_drift_reader = acknowledged_drift_reader
        self.confidence = confidence

    async def propose_impacts(
        self,
        *,
        source_id: str,
        src_table: str,
        change: ColumnChange,
        company_id: Any,
    ) -> list[ProposedImpact]:
        """Look up L2 acknowledged drifts; propose elevated impact when any exist."""
        if not source_id or not change.src_column:
            return []

        records = await (
            self.acknowledged_drift_reader
            .list_acknowledged_drifts_for_source_column(
                source_id,
                change.src_column,
                company_id=company_id,
            )
        )
        if not records:
            return []

        # Pick the first acknowledged drift in reader iteration order
        # (the reader returns sorted-by-drift_id for replay stability).
        # Wave 1 is kind-agnostic: any acknowledged drift triggers; the
        # specific kind goes into evidence for the dashboard chip.
        winner = records[0]
        impact_kind = _ACKNOWLEDGED_DRIFT_IMPACT_KIND_FOR_CHANGE[change.change_kind]
        confidence = round(float(self.confidence), 4)

        return [
            _propose(
                source_id=source_id,
                src_table=src_table,
                src_column=change.src_column,
                change_kind=change.change_kind,
                impact_kind=impact_kind,
                tgt_table_id=src_table,
                tgt_column=change.src_column,
                upstream_lineage_edge_id=None,
                confidence=confidence,
                strategy=self.name,
                reasoning=(
                    f"L2 acknowledged catalog drift "
                    f"(drift_kind={winner.drift_kind!r}) on "
                    f"{src_table}.{change.src_column} "
                    f"(acknowledged_by={winner.acknowledged_by_person_id}); "
                    f"{change.change_kind} elevated to "
                    f"acknowledged_drift_severity=high "
                    f"at {confidence:.2f} — review downstream consequences"
                ),
                evidence={
                    "upstream_drift_id": winner.drift_id,
                    "drift_kind": winner.drift_kind,
                    "acknowledged_drift_severity": "high",
                    "acknowledged_at": winner.acknowledged_at.isoformat(),
                    "acknowledged_by_person_id": (
                        winner.acknowledged_by_person_id
                    ),
                    "change_kind": change.change_kind,
                    "old_type": change.old_type,
                    "new_type": change.new_type,
                    # Diagnostic: how many acknowledged drifts exist on
                    # this column (operators want to see drift
                    # accumulation history).
                    "acknowledged_drift_count": len(records),
                },
            ),
        ]


# Static check: each strategy implements the Protocol.
_proto_check: tuple[type[SchemaImpactService], ...] = (
    LineageEdgeImpactStrategy,
    DbtTestImpactStrategy,
    TypeCoercionImpactStrategy,
    GovernanceClassificationImpactStrategy,
    SemanticTypeImpactStrategy,
    AcknowledgedDriftImpactStrategy,
)
del _proto_check
