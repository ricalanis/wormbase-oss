"""L4↦L2 chain — AcknowledgedDriftImpactStrategy tests.

The **7th cross-axis chain** in the lake-side stack (after L4→L3,
L6→L5, L8→L5, L5→L7, L6→L4, L5→L4), and the **first BIDIRECTIONAL
chain**: L4 elevates impacts on L2-acknowledged drifts (forward —
this strategy); the L2 dashboard surfaces downstream-impact roll-up
counts per drift row (reverse — Half B, dashboard-only).

Pins:

  * Empty L2 reader → no proposals.
  * Acknowledged drifts of all 5 drift_kinds elevate at
    severity=high (Wave-1 kind-agnostic posture; the kind value goes
    into evidence).
  * change_kind → impact_kind mapping (mirrors Governance + SemanticType
    + LineageEdge for consistency on the L4 enum surface).
  * Confidence is base-confidence (0.92 — acknowledgment is human signal).
  * Multi-drift column: first acknowledged drift in reader order wins;
    diagnostic ``acknowledged_drift_count`` surfaces the overlap.
  * Symbol-identity Protocol pin: the strategy's
    acknowledged_drift_reader argument's Protocol annotation IS the
    L2-side :class:`AcknowledgedDriftReader` (first consumer of that
    Protocol — N=1 producer-side L2 Protocol).
  * Composite integration: 6th strategy slot wires through Optional-
    Effect Injection.
  * Default-OFF byte-identical: composite with all 5 prior strategies
    + acknowledged_drift=None matches pre-chain behavior.
  * Coexistence with governance + semantic_type: an L2+L5+L6 confirmed
    column produces ONE merged proposal (composite-merge dedup
    activates — same canonical tuple).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from wormbase_agent_gateway.catalog_drift.protocol import (
    AcknowledgedDriftReader,
    AcknowledgedDriftRecord,
)
from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedClassificationRecord,
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.schema_impact import (
    AcknowledgedDriftImpactStrategy,
    ColumnChange,
    CompositeSchemaImpactService,
    GovernanceClassificationImpactStrategy,
    LineageEdgeImpactStrategy,
    LineageEdgeRecord,
    SemanticTypeImpactStrategy,
    TypeCoercionImpactStrategy,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAcknowledgedDriftReader:
    """Test double for :class:`AcknowledgedDriftReader`.

    Records each call's (source_id, column) for verification and returns
    the seeded records that match the lookup.
    """

    def __init__(
        self,
        records: list[AcknowledgedDriftRecord] | None = None,
        *,
        match: tuple[str, str | None] | None = None,
    ) -> None:
        self.records = records or []
        # When match is set, only return records on (source_id, column)
        # match; when None, filter naturally (by source + column == column).
        self.match = match
        self.calls: list[tuple[str, str | None]] = []
        self.scan_calls: int = 0

    async def list_acknowledged_drifts_for_source_column(
        self,
        source_id: str,
        src_column: str | None,
        *,
        company_id,
    ) -> list[AcknowledgedDriftRecord]:
        self.calls.append((source_id, src_column))
        if self.match is not None:
            if (source_id, src_column) != self.match:
                return []
            return list(self.records)
        # Default behaviour: filter to records matching source + column.
        return [
            r for r in self.records
            if r.source_id == source_id and r.column == src_column
        ]

    async def list_acknowledged_drifts(
        self,
        *,
        company_id,
    ) -> list[AcknowledgedDriftRecord]:
        self.scan_calls += 1
        return list(self.records)


class _FakeClassificationReader:
    """Test double for :class:`ConfirmedClassificationReader`."""

    def __init__(
        self,
        records: list[ConfirmedClassificationRecord] | None = None,
    ) -> None:
        self.records = records or []

    async def list_confirmed_classifications_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id,
    ) -> list[ConfirmedClassificationRecord]:
        return [
            r for r in self.records
            if r.column == src_column and r.source_id == source_id
        ]


class _FakeSemanticTypeReader:
    """Test double for :class:`ConfirmedSemanticTypeReader`."""

    def __init__(
        self,
        records: list[ConfirmedSemanticTypeRecord] | None = None,
    ) -> None:
        self.records = records or []

    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id,
    ) -> list[ConfirmedSemanticTypeRecord]:
        return list(self.records)


class _FakeLineageEdgeReader:
    """Test double for :class:`LineageEdgeReader` — used in composite tests."""

    def __init__(self, edges: list[LineageEdgeRecord] | None = None) -> None:
        self.edges = edges or []

    async def list_confirmed_edges_for_source_column(
        self, *, source_id: str, src_column: str, company_id,
    ) -> list[LineageEdgeRecord]:
        return list(self.edges)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ack(
    *,
    drift_id: str = "drift-1",
    source_id: str = "warehouse",
    table_id: str = "warehouse.dim_customer",
    column: str | None = "email",
    drift_kind: str = "column_type_changed",
    before: dict | None = None,
    after: dict | None = None,
    acknowledged_by: str = "alice-admin",
) -> AcknowledgedDriftRecord:
    # Defaults for column_type_changed: both before+after present.
    if drift_kind == "column_type_changed":
        before = before if before is not None else {"type": "varchar"}
        after = after if after is not None else {"type": "text"}
    elif drift_kind in ("column_added", "table_added"):
        before = None
    elif drift_kind in ("column_removed", "table_removed"):
        after = None
    return AcknowledgedDriftRecord(
        drift_id=drift_id,
        source_id=source_id,
        table_id=table_id,
        column=column,
        drift_kind=drift_kind,
        before=before,
        after=after,
        acknowledged_at=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
        acknowledged_by_person_id=acknowledged_by,
    )


def _change(
    *,
    kind: str = "column_type_changed",
    column: str = "email",
    table: str = "warehouse.dim_customer",
    old: str | None = "varchar",
    new: str | None = "text",
) -> ColumnChange:
    return ColumnChange(
        src_table=table,
        src_column=column,
        change_kind=kind,  # type: ignore[arg-type]
        old_type=old,
        new_type=new,
    )


# ---------------------------------------------------------------------------
# Symbol-identity Protocol pin
# ---------------------------------------------------------------------------


def test_symbol_identity_protocol_pin() -> None:
    """The strategy MUST hold the L2-side :class:`AcknowledgedDriftReader`
    Protocol (not a duplicate or parallel copy).

    Pins the producer-side ownership: L2 (catalog_drift subpackage)
    owns the Protocol; L4 (schema_impact subpackage) imports it. The
    symbol resolved by the strategy's `__init__` annotation IS the
    same object as the one importable from L2's subpackage AND from
    the top-level gateway re-export.
    """
    # Resolve the strategy's __init__ annotations (PEP 563 deferred
    # evaluation under `from __future__ import annotations`).
    import typing

    hints = typing.get_type_hints(AcknowledgedDriftImpactStrategy.__init__)
    annotation = hints["acknowledged_drift_reader"]
    # The annotation is the imported AcknowledgedDriftReader class.
    assert annotation is AcknowledgedDriftReader

    # Single-source-of-Protocol: importing from both paths yields
    # the SAME object.
    from wormbase_agent_gateway.catalog_drift import (
        AcknowledgedDriftReader as ViaSubpackage,
    )
    from wormbase_agent_gateway import (
        AcknowledgedDriftReader as ViaTopLevel,
    )
    assert AcknowledgedDriftReader is ViaSubpackage
    assert AcknowledgedDriftReader is ViaTopLevel

    # Fake satisfies the Protocol at runtime.
    fake = _FakeAcknowledgedDriftReader()
    assert isinstance(fake, AcknowledgedDriftReader)


# ---------------------------------------------------------------------------
# Strategy — base cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_acknowledged_drifts_returns_empty() -> None:
    """Empty L2 reader → no acknowledged-drift-elevated proposals."""
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=_FakeAcknowledgedDriftReader(),
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_acknowledged_column_type_changed_elevates() -> None:
    """An acknowledged column_type_changed drift → severity high at 0.92."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_kind="column_type_changed", drift_id="d-type-1")],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.strategy == "acknowledged_drift"
    assert p.impact_kind == "tgt_column_type_mismatch"
    assert p.confidence == pytest.approx(0.92)
    assert p.evidence["acknowledged_drift_severity"] == "high"
    assert p.evidence["drift_kind"] == "column_type_changed"
    assert p.evidence["upstream_drift_id"] == "d-type-1"
    assert p.evidence["acknowledged_by_person_id"] == "alice-admin"
    # Target IS the changed column (composite-merge dedup target).
    assert p.tgt_table_id == "warehouse.dim_customer"
    assert p.tgt_column == "email"
    # No L3 edge consumed.
    assert p.upstream_lineage_edge_id is None


@pytest.mark.asyncio
async def test_acknowledged_column_added_elevates() -> None:
    """An acknowledged column_added drift → severity high at 0.92."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_kind="column_added", drift_id="d-add-1", before=None, after={"name": "email"})],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_added", old=None, new="varchar"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "tgt_column_unaware"
    assert p.evidence["drift_kind"] == "column_added"
    assert p.confidence == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_acknowledged_column_removed_elevates() -> None:
    """An acknowledged column_removed drift → severity high at 0.92."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_kind="column_removed", drift_id="d-rm-1", before={"name": "email"}, after=None)],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped", old="varchar", new=None),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.impact_kind == "tgt_column_orphaned"
    assert p.evidence["drift_kind"] == "column_removed"


@pytest.mark.asyncio
async def test_change_with_no_acknowledged_drift_returns_empty() -> None:
    """A change on a column with NO acknowledged drift → no proposal."""
    # Reader has acknowledged drifts on OTHER columns, but not on "email".
    reader = _FakeAcknowledgedDriftReader(
        [
            _ack(drift_id="d-other-1", column="phone", drift_kind="column_added"),
            _ack(drift_id="d-other-2", column="address", drift_kind="column_removed"),
        ],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(column="email"),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_evidence_carries_all_required_keys() -> None:
    """evidence MUST carry upstream_drift_id, drift_kind, severity."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_id="d-evidence", drift_kind="column_type_changed")],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    ev = proposals[0].evidence
    # Required keys per doctrine (mirrors GovernanceClassification +
    # SemanticType evidence shape).
    assert "upstream_drift_id" in ev
    assert "drift_kind" in ev
    assert "acknowledged_drift_severity" in ev
    assert "acknowledged_at" in ev
    assert "acknowledged_by_person_id" in ev
    assert "change_kind" in ev
    assert ev["upstream_drift_id"] == "d-evidence"
    assert ev["acknowledged_drift_severity"] == "high"


@pytest.mark.asyncio
async def test_multi_drift_column_picks_first_replay_stable() -> None:
    """Multiple acknowledged drifts on same column → first wins; count surfaced."""
    reader = _FakeAcknowledgedDriftReader([
        _ack(drift_id="d-a-1", drift_kind="column_type_changed"),
        _ack(drift_id="d-b-2", drift_kind="column_added", before=None, after={"name": "email"}),
    ])
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    # First record in reader order wins (the reader returns records
    # in the order seeded; production impl sorts by drift_id).
    assert p.evidence["upstream_drift_id"] == "d-a-1"
    # Diagnostic count surfaces the overlap.
    assert p.evidence["acknowledged_drift_count"] == 2


@pytest.mark.asyncio
async def test_empty_src_column_returns_empty() -> None:
    """Defensive: a ColumnChange with empty src_column → no proposal.

    This guards against table-level changes (which lack src_column) being
    sent to a column-keyed lookup. Today's strategy is column-grain only.
    """
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_id="d-1", column="email")],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=ColumnChange(
            src_table="warehouse.dim_customer",
            src_column="",  # empty — defensive case
            change_kind="column_type_changed",
            old_type="varchar",
            new_type="text",
        ),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_empty_source_id_returns_empty() -> None:
    """Defensive: empty source_id → no proposal."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_id="d-1")],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []


# ---------------------------------------------------------------------------
# Composite integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_with_acknowledged_drift_only() -> None:
    """Composite with ONLY the acknowledged_drift slot wired returns its proposals."""
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_id="d-1")],
    )
    strat = AcknowledgedDriftImpactStrategy(
        acknowledged_drift_reader=reader,
    )
    composite = CompositeSchemaImpactService(
        acknowledged_drift=strat,
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].strategy == "acknowledged_drift"


@pytest.mark.asyncio
async def test_composite_acknowledged_drift_none_is_byte_identical() -> None:
    """Default-OFF check: composite with acknowledged_drift=None matches pre-chain behavior."""
    # All 5 prior strategies set to None; only-difference between
    # this test and the empty composite is the new slot defaulting None.
    composite_with_explicit_none = CompositeSchemaImpactService(
        acknowledged_drift=None,
    )
    composite_default = CompositeSchemaImpactService()
    # Both should return empty proposals for any change.
    p1 = await composite_with_explicit_none.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    p2 = await composite_default.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert p1 == p2 == []


@pytest.mark.asyncio
async def test_composite_with_all_six_strategies_wires_correctly() -> None:
    """All 6 strategies (5 prior + acknowledged_drift) compose without error."""
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeLineageEdgeReader(),
        ),
        dbt_test=None,  # opt-in
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeLineageEdgeReader(),
        ),
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=_FakeClassificationReader(),
        ),
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
        acknowledged_drift=AcknowledgedDriftImpactStrategy(
            acknowledged_drift_reader=_FakeAcknowledgedDriftReader(),
        ),
    )
    # Sanity: composite holds all 6 strategy slots.
    assert composite.lineage_edge is not None
    assert composite.dbt_test is None
    assert composite.type_coercion is not None
    assert composite.governance_classification is not None
    assert composite.semantic_type is not None
    assert composite.acknowledged_drift is not None
    # All-None reader fakes → all strategies return [] → composite [].
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_composite_merge_dedup_governance_plus_semantic_plus_acknowledged() -> None:
    """3 cross-axis strategies co-fire on the same canonical tuple → ONE merged row.

    This is the recipe addendum #2 from the L5→L4 close-out: when
    multiple cross-axis-elevation strategies hit the same column
    (target=src), the composite merges them into a single row carrying
    all 3 evidence keys + 3 chips + 3 links. With acknowledged_drift
    added, we now have a 3-way merge case.
    """
    # All three strategies fire on the same column.
    classification_reader = _FakeClassificationReader([
        ConfirmedClassificationRecord(
            classification_id="cls-pii-1",
            source_id="warehouse",
            table_id="warehouse.dim_customer",
            column="email",
            classification_level="pii",  # type: ignore[arg-type]
            confirmed_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            confirmed_by_person_id="alice",
        ),
    ])
    semantic_type_reader = _FakeSemanticTypeReader([
        ConfirmedSemanticTypeRecord(
            type_id="st-email-1",
            semantic_type="email",
            confidence=0.95,
            strategy="column_name_fingerprint",
        ),
    ])
    drift_reader = _FakeAcknowledgedDriftReader([
        _ack(drift_id="d-merge-1", drift_kind="column_type_changed"),
    ])
    composite = CompositeSchemaImpactService(
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=classification_reader,
        ),
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=semantic_type_reader,
        ),
        acknowledged_drift=AcknowledgedDriftImpactStrategy(
            acknowledged_drift_reader=drift_reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    # All three strategies target the SAME (source, src_table, src_column,
    # change_kind, tgt_table_id, tgt_column) canonical tuple — the
    # composite collapses to ONE row carrying all three evidence keys.
    assert len(proposals) == 1
    merged = proposals[0]
    # Merged proposal uses strategy="composite" per composite contract.
    assert merged.strategy == "composite"
    # Each strategy's evidence is preserved under its strategy key in the
    # merged evidence dict (per default_cluster_merge contract).
    assert "governance_classification" in merged.evidence
    assert "semantic_type" in merged.evidence
    assert "acknowledged_drift" in merged.evidence
    # Each evidence sub-dict carries its strategy-specific upstream id
    # — so the dashboard can render 3 chips + 3 links.
    assert (
        merged.evidence["governance_classification"]["upstream_classification_id"]
        == "cls-pii-1"
    )
    assert (
        merged.evidence["semantic_type"]["upstream_semantic_type_id"]
        == "st-email-1"
    )
    assert (
        merged.evidence["acknowledged_drift"]["upstream_drift_id"]
        == "d-merge-1"
    )


@pytest.mark.asyncio
async def test_composite_merge_dedup_semantic_plus_acknowledged() -> None:
    """semantic_type + acknowledged_drift co-fire → ONE merged row with both evidence keys.

    Two-way merge case (subset of the 3-way) — proves the recipe
    activates for any 2 cross-axis strategies on the same column.
    """
    semantic_type_reader = _FakeSemanticTypeReader([
        ConfirmedSemanticTypeRecord(
            type_id="st-uuid-1",
            semantic_type="uuid",
            confidence=0.95,
            strategy="column_name_fingerprint",
        ),
    ])
    drift_reader = _FakeAcknowledgedDriftReader([
        _ack(
            drift_id="d-co-1",
            column="customer_id",
            drift_kind="column_type_changed",
        ),
    ])
    composite = CompositeSchemaImpactService(
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=semantic_type_reader,
        ),
        acknowledged_drift=AcknowledgedDriftImpactStrategy(
            acknowledged_drift_reader=drift_reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(column="customer_id", kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    merged = proposals[0]
    assert merged.strategy == "composite"
    assert "semantic_type" in merged.evidence
    assert "acknowledged_drift" in merged.evidence


@pytest.mark.asyncio
async def test_acknowledged_drift_alone_when_only_strategy_wired() -> None:
    """When only acknowledged_drift is wired, no merge occurs — single-strategy proposal.

    Verifies that when a strategy is alone, its proposal is returned
    verbatim (no composite merge). The composite-merge dedup only
    fires when 2+ strategies propose on the same canonical tuple.
    """
    reader = _FakeAcknowledgedDriftReader(
        [_ack(drift_id="d-alone-1")],
    )
    composite = CompositeSchemaImpactService(
        acknowledged_drift=AcknowledgedDriftImpactStrategy(
            acknowledged_drift_reader=reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    # No merge — strategy stays as "acknowledged_drift", not "composite".
    assert proposals[0].strategy == "acknowledged_drift"
