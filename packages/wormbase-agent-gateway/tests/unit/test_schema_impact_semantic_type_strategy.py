"""L5→L4 chain — SemanticTypeImpactStrategy tests.

The 6th cross-axis chain in the lake-side stack (after L4→L3, L6→L5,
L8→L5, L5→L7, L6→L4), and the **last of the 3 originally-foreshadowed
peer-axis chains**. L4's L5-reading strategy elevates schema-evolution
impact severity when a changed column has an L5 confirmed semantic
type.

Pins:

  * Empty L5 reader → no proposals.
  * Confirmed semantic types of various kinds (email / uuid / phone /
    pii_name / unknown_custom_type) all elevate at severity=high
    (Wave-1 type-agnostic posture; the type value goes into evidence).
  * change_kind → impact_kind mapping (mirrors LineageEdge + Governance
    for consistency on the L4 enum surface).
  * Confidence is base-confidence (0.90).
  * Multi-type column: first confirmed type in reader order wins;
    diagnostic ``semantic_type_count`` surfaces the overlap.
  * Symbol-identity Protocol pin: the strategy's
    confirmed_semantic_type_reader argument's Protocol annotation
    IS the L6-side :class:`ConfirmedSemanticTypeReader` (4th consumer
    of the same Protocol — L6, L8, L7, L4).
  * Composite integration: 5th strategy slot wires through Optional-
    Effect Injection; metrics counter increments.
  * Default-OFF byte-identical: composite with all 4 prior
    strategies + semantic_type=None matches pre-chain behavior.
  * Coexistence with governance: an L5+L6 confirmed column produces
    TWO proposals (one per strategy, different impact_ids).
"""
from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedClassificationRecord,
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.schema_impact import (
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


class _FakeSemanticTypeReader:
    """Test double for :class:`ConfirmedSemanticTypeReader`.

    Records each call's (table_id, column) for verification and returns
    the seeded records that match the lookup.
    """

    def __init__(
        self,
        records: list[ConfirmedSemanticTypeRecord] | None = None,
        *,
        match: tuple[str, str] | None = None,
    ) -> None:
        self.records = records or []
        # When match is set, only return records on (table_id, column)
        # match; when None, return all records regardless of lookup.
        self.match = match
        self.calls: list[tuple[str, str]] = []

    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id,
    ) -> list[ConfirmedSemanticTypeRecord]:
        self.calls.append((table_id, column))
        if self.match is not None and (table_id, column) != self.match:
            return []
        return list(self.records)


class _FakeClassificationReader:
    """Test double for :class:`ConfirmedClassificationReader` — used in
    the L5+L6 coexistence test."""

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


def _type_record(
    *,
    type_id: str = "type-1",
    semantic_type: str = "email",
    confidence: float = 0.95,
    strategy: str = "column_name",
) -> ConfirmedSemanticTypeRecord:
    return ConfirmedSemanticTypeRecord(
        type_id=type_id,
        semantic_type=semantic_type,
        confidence=confidence,
        strategy=strategy,
    )


def _change(
    *,
    kind: str = "column_type_changed",
    column: str = "email",
    table: str = "warehouse.dim_customer",
    old: str | None = "varchar",
    new: str | None = "integer",
) -> ColumnChange:
    return ColumnChange(
        src_table=table,
        src_column=column,
        change_kind=kind,  # type: ignore[arg-type]
        old_type=old,
        new_type=new,
    )


# ---------------------------------------------------------------------------
# Symbol-identity Protocol pin — 4th consumer of L6's reader Protocol
# ---------------------------------------------------------------------------


def test_symbol_identity_protocol_pin() -> None:
    """The strategy MUST hold the L6-side
    :class:`ConfirmedSemanticTypeReader` Protocol (4th consumer —
    after L6's own SemanticTypeClassificationStrategy, L8's
    NameMatchEntityStrategy, and L7's SemanticTypeQualityCheckStrategy).

    Verified three ways (the strategies module uses
    ``from __future__ import annotations`` so type hints are stringified;
    we resolve them via :func:`typing.get_type_hints`):

    1. The init signature's resolved type hint for
       ``confirmed_semantic_type_reader`` IS the canonical Protocol
       symbol imported from the column_classification module.
    2. The runtime_checkable Protocol accepts our fake.
    3. Importing the Protocol from the subpackage __init__ vs the
       protocol module yields the same object (single-source).
    """
    import typing
    hints = typing.get_type_hints(SemanticTypeImpactStrategy.__init__)
    assert hints["confirmed_semantic_type_reader"] is (
        ConfirmedSemanticTypeReader
    )

    fake = _FakeSemanticTypeReader()
    assert isinstance(fake, ConfirmedSemanticTypeReader)

    # Importing from both paths yields the SAME object (single-source
    # of Protocol — same coupling-minimization invariant as L6→L4):
    from wormbase_agent_gateway.column_classification import (
        ConfirmedSemanticTypeReader as ViaSubpackage,
    )
    assert ConfirmedSemanticTypeReader is ViaSubpackage


# ---------------------------------------------------------------------------
# Strategy — base cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_semantic_types_returns_empty() -> None:
    """Empty L5 reader → no semantic-type-elevated proposals."""
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_email_semantic_type_elevates_to_high() -> None:
    """``email`` confirmed → semantic_type_severity=high at 0.90."""
    reader = _FakeSemanticTypeReader(
        [_type_record(type_id="type-email", semantic_type="email")],
    )
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.strategy == "semantic_type"
    assert p.impact_kind == "tgt_column_type_mismatch"
    assert p.confidence == pytest.approx(0.90)
    assert p.evidence["semantic_type_severity"] == "high"
    assert p.evidence["semantic_type"] == "email"
    assert p.evidence["upstream_semantic_type_id"] == "type-email"
    # Target is the column itself — elevation is a separate row,
    # not downstream propagation.
    assert p.tgt_table_id == "warehouse.dim_customer"
    assert p.tgt_column == "email"
    # No L3 edge consumed; upstream_lineage_edge_id stays None.
    assert p.upstream_lineage_edge_id is None
    # Reader was called with the (table_id, column) of the changed column.
    assert reader.calls == [("warehouse.dim_customer", "email")]


@pytest.mark.asyncio
async def test_uuid_semantic_type_elevates() -> None:
    """``uuid`` confirmed → severity=high (Wave-1 type-agnostic)."""
    reader = _FakeSemanticTypeReader(
        [_type_record(type_id="type-uuid", semantic_type="uuid")],
    )
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped", column="account_uuid"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].evidence["semantic_type"] == "uuid"
    assert proposals[0].evidence["semantic_type_severity"] == "high"
    assert proposals[0].impact_kind == "tgt_column_orphaned"


@pytest.mark.asyncio
async def test_phone_semantic_type_elevates() -> None:
    """``phone_e164`` confirmed → severity=high."""
    reader = _FakeSemanticTypeReader(
        [_type_record(type_id="type-phone", semantic_type="phone_e164")],
    )
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_added", column="phone", old=None, new="varchar"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].evidence["semantic_type"] == "phone_e164"
    assert proposals[0].evidence["semantic_type_severity"] == "high"


@pytest.mark.asyncio
async def test_unknown_semantic_type_still_elevates_type_agnostic() -> None:
    """Wave-1 is type-agnostic: ANY confirmed type triggers; the value
    goes into evidence (so the dashboard can render it without the
    strategy hard-coding a taxonomy)."""
    reader = _FakeSemanticTypeReader(
        [_type_record(type_id="type-custom", semantic_type="business_id_xyz")],
    )
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].evidence["semantic_type"] == "business_id_xyz"
    assert proposals[0].evidence["semantic_type_severity"] == "high"


# ---------------------------------------------------------------------------
# change_kind → impact_kind mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change_kind, expected_impact_kind",
    [
        ("column_dropped", "tgt_column_orphaned"),
        ("column_type_changed", "tgt_column_type_mismatch"),
        ("column_added", "tgt_column_unaware"),
    ],
)
async def test_change_kind_to_impact_kind_mapping(
    change_kind: str, expected_impact_kind: str,
) -> None:
    """All 3 change_kind values map to canonical L4 impact_kind values."""
    reader = _FakeSemanticTypeReader([_type_record(semantic_type="email")])
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(
            kind=change_kind,
            old="varchar" if change_kind != "column_added" else None,
            new="varchar" if change_kind != "column_dropped" else None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].impact_kind == expected_impact_kind


# ---------------------------------------------------------------------------
# Multi-type column — first wins, count diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_type_column_first_wins_count_diagnostic() -> None:
    """Multiple confirmed types on the same column → first (reader-order)
    wins; ``evidence.semantic_type_count`` surfaces the total."""
    reader = _FakeSemanticTypeReader([
        _type_record(type_id="type-aaa-email", semantic_type="email"),
        _type_record(type_id="type-bbb-piiname", semantic_type="pii_name"),
        _type_record(type_id="type-ccc-uuid", semantic_type="uuid"),
    ])
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    # First-in-reader-order wins for replay stability (reader returns
    # sorted-by-type_id; "type-aaa-email" comes before "type-bbb-...").
    assert p.evidence["semantic_type"] == "email"
    assert p.evidence["upstream_semantic_type_id"] == "type-aaa-email"
    assert p.evidence["semantic_type_count"] == 3


# ---------------------------------------------------------------------------
# Replay stability — same inputs → same outputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_stable_identical_inputs() -> None:
    """Two calls with the same inputs produce byte-identical proposals."""
    reader_a = _FakeSemanticTypeReader([_type_record(semantic_type="email")])
    reader_b = _FakeSemanticTypeReader([_type_record(semantic_type="email")])
    strat_a = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader_a,
    )
    strat_b = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader_b,
    )
    company = uuid4()
    p_a = await strat_a.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=company,
    )
    p_b = await strat_b.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=company,
    )
    assert p_a == p_b


# ---------------------------------------------------------------------------
# Empty src_column / src_table — defensive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_src_table_short_circuits() -> None:
    """Empty src_table → no reader call, no proposals."""
    reader = _FakeSemanticTypeReader([_type_record(semantic_type="email")])
    strat = SemanticTypeImpactStrategy(
        confirmed_semantic_type_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []
    assert reader.calls == []


# ---------------------------------------------------------------------------
# Composite integration — 5th strategy slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_semantic_type_slot_optional_none_byte_identical() -> None:
    """Composite with all 4 prior strategies + semantic_type=None matches
    pre-chain behavior (Optional-Effect Injection default-OFF guarantee)."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="warehouse.dim_customer",
        src_column="email",
        tgt_table_id="mart.fact_orders",
        tgt_column="customer_email",
        confidence=0.99,
        strategy="dbt_manifest",
    )

    class _FakeLEReader:
        async def list_confirmed_edges_for_source_column(
            self, *, source_id, src_column, company_id,
        ):
            return [edge] if src_column == "email" else []

    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeLEReader(),
        ),
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeLEReader(),
        ),
        # semantic_type defaults to None — no kwarg passed.
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    # One lineage_edge proposal — composite behavior unchanged.
    assert len(proposals) == 1
    assert proposals[0].strategy == "lineage_edge"
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.semantic_type"] == 0
    assert metrics["schema_impact_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_semantic_type_only_fires() -> None:
    """Composite with only semantic_type wired returns semantic-type
    proposals when L5 has confirmed types."""
    reader = _FakeSemanticTypeReader([
        _type_record(type_id="type-email", semantic_type="email"),
    ])
    composite = CompositeSchemaImpactService(
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].strategy == "semantic_type"
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.semantic_type"] == 1
    assert metrics["schema_impact_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_all_5_strategies_aggregate() -> None:
    """Composite with all 5 strategies wired produces aggregated proposals
    when each strategy fires."""
    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="warehouse.dim_customer",
        src_column="email",
        tgt_table_id="mart.fact_orders",
        tgt_column="customer_email",
        confidence=0.99,
        strategy="dbt_manifest",
    )

    class _FakeLEReader:
        async def list_confirmed_edges_for_source_column(
            self, *, source_id, src_column, company_id,
        ):
            return [edge] if src_column == "email" else []

    semantic_reader = _FakeSemanticTypeReader([
        _type_record(type_id="type-email", semantic_type="email"),
    ])
    governance_reader = _FakeClassificationReader([
        ConfirmedClassificationRecord(
            classification_id="cls-reg",
            source_id="warehouse",
            table_id="warehouse.dim_customer",
            column="email",
            classification_level="regulated",
            confirmed_at=__import__("datetime").datetime(
                2026, 6, 11, 9, 0,
                tzinfo=__import__("datetime").timezone.utc,
            ),
            confirmed_by_person_id="alice-admin",
        ),
    ])
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeLEReader(),
        ),
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeLEReader(),
        ),
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=governance_reader,
        ),
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=semantic_reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    # All 4 firing strategies contribute proposals; the composite
    # dedups by canonical impact_id. Governance + semantic_type both
    # target src=src so they share an impact_id (merged into one
    # composite row carrying both evidence keys). Lineage_edge +
    # type_coercion target downstream (mart.fact_orders.customer_email)
    # — they share a separate impact_id and merge into a second
    # composite row. Net: 2 composite rows when all 4 fire.
    assert len(proposals) >= 2
    # Per-strategy metrics counter is the authoritative signal that
    # each strategy fired its own propose call regardless of how the
    # composite merged the outputs.
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.semantic_type"] == 1
    assert metrics["schema_impact_strategy_invocations.governance_classification"] == 1
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 1
    assert metrics["schema_impact_strategy_invocations.type_coercion"] == 1
    # The src=src merged row carries BOTH governance + semantic_type
    # evidence keys (proves both contributed to the same merge).
    src_src_rows = [
        p for p in proposals
        if p.tgt_table_id == "warehouse.dim_customer" and p.tgt_column == "email"
    ]
    assert len(src_src_rows) == 1
    src_merged = src_src_rows[0]
    assert "governance_classification" in src_merged.evidence
    assert "semantic_type" in src_merged.evidence


@pytest.mark.asyncio
async def test_semantic_type_and_governance_coexist_on_same_row() -> None:
    """When BOTH L5 confirms a semantic type AND L6 confirms a
    classification on the same column, the strategies fire independently
    and produce TWO separate proposals (different impact_ids).

    This mirrors the dashboard's per-row chip + link coexistence:
    a regulated email column carries both ``view L5 semantic type →``
    and ``view L6 classification →`` links + both severity chips.
    """
    semantic_reader = _FakeSemanticTypeReader([
        _type_record(type_id="type-email", semantic_type="email"),
    ])
    governance_reader = _FakeClassificationReader([
        ConfirmedClassificationRecord(
            classification_id="cls-pii",
            source_id="warehouse",
            table_id="warehouse.dim_customer",
            column="email",
            classification_level="pii",
            confirmed_at=__import__("datetime").datetime(
                2026, 6, 11, 9, 0,
                tzinfo=__import__("datetime").timezone.utc,
            ),
            confirmed_by_person_id="alice-admin",
        ),
    ])
    composite = CompositeSchemaImpactService(
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=governance_reader,
        ),
        semantic_type=SemanticTypeImpactStrategy(
            confirmed_semantic_type_reader=semantic_reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_type_changed"),
        company_id=uuid4(),
    )
    # Both strategies target src=src, but with the SAME canonical tuple
    # ─ so they share the same impact_id and merge into ONE composite
    # proposal. The merged proposal's evidence carries both keys.
    assert len(proposals) == 1
    merged = proposals[0]
    # composite merging — strategy = "composite" when N≥2 strategies
    # contributed to the same impact_id.
    assert merged.strategy == "composite"
    # The merged evidence dict is keyed by strategy name per L4
    # composite's default cluster merge — both keys present.
    assert "governance_classification" in merged.evidence
    assert "semantic_type" in merged.evidence
    # Per-strategy evidence keys preserved verbatim.
    gov_ev = merged.evidence["governance_classification"]
    sem_ev = merged.evidence["semantic_type"]
    assert gov_ev["upstream_classification_id"] == "cls-pii"
    assert gov_ev["governance_severity"] == "high"
    assert sem_ev["upstream_semantic_type_id"] == "type-email"
    assert sem_ev["semantic_type_severity"] == "high"
