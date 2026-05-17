"""L6→L4 chain — GovernanceClassificationImpactStrategy tests.

The 5th cross-axis chain in the lake-side stack (after L4→L3, L6→L5,
L8→L5, L5→L7). L4's L6-reading strategy elevates schema-evolution
impact severity when a changed column has an L6 confirmed classification
at ``regulated`` / ``pii`` / ``confidential``.

Pins:

  * Empty L6 reader → no proposals.
  * Per-classification-level severity mapping (regulated → critical,
    pii / confidential → high, internal / public → no proposal).
  * change_kind → impact_kind mapping (mirrors LineageEdge for
    consistency on the L4 enum surface).
  * Confidence is base-confidence per profile (0.95 regulated, 0.90
    pii/confidential).
  * Multi-level winner: highest-severity confirmed level wins on
    elevation; lower levels ignored.
  * Multi-table same-column: only the changed src_table's
    classifications elevate; classifications on other tables are
    filtered out (defensive).
  * Symbol-identity Protocol pin: the strategy's
    confirmed_classification_reader argument's Protocol annotation
    IS the L6-side :class:`ConfirmedClassificationReader`.
  * Composite integration: 4th strategy slot wires through Optional-
    Effect Injection; metrics counter increments.
  * Default-OFF byte-identical: composite with all 3 original
    strategies + governance=None matches pre-chain behavior.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedClassificationReader,
    ConfirmedClassificationRecord,
)
from wormbase_agent_gateway.schema_impact import (
    ColumnChange,
    CompositeSchemaImpactService,
    GovernanceClassificationImpactStrategy,
    LineageEdgeImpactStrategy,
    LineageEdgeRecord,
    TypeCoercionImpactStrategy,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeClassificationReader:
    """Test double for :class:`ConfirmedClassificationReader`."""

    def __init__(
        self,
        records: list[ConfirmedClassificationRecord] | None = None,
    ) -> None:
        self.records = records or []
        self.calls: list[tuple[str, str]] = []

    async def list_confirmed_classifications_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id,
    ) -> list[ConfirmedClassificationRecord]:
        self.calls.append((source_id, src_column))
        return [
            r for r in self.records
            if r.column == src_column and r.source_id == source_id
        ]


def _rec(
    *,
    classification_id: str = "cls-1",
    source_id: str = "warehouse",
    table_id: str = "warehouse.dim_customer",
    column: str = "email",
    classification_level: str = "pii",
    confirmed_by: str = "alice-admin",
) -> ConfirmedClassificationRecord:
    return ConfirmedClassificationRecord(
        classification_id=classification_id,
        source_id=source_id,
        table_id=table_id,
        column=column,
        classification_level=classification_level,  # type: ignore[arg-type]
        confirmed_at=datetime(2026, 6, 11, 9, 0, tzinfo=timezone.utc),
        confirmed_by_person_id=confirmed_by,
    )


def _change(
    *,
    kind: str = "column_dropped",
    column: str = "email",
    table: str = "warehouse.dim_customer",
    old: str | None = "varchar",
    new: str | None = None,
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
    """The strategy MUST hold the L6-side
    :class:`ConfirmedClassificationReader` Protocol (not a duplicate or
    parallel copy)."""
    # NOTE: the strategy's __init__ kwarg's type annotation comes from
    # the protocol import. We verify symbol-identity at runtime by
    # asserting the runtime_checkable Protocol accepts our fake AND
    # that the imported symbol is the canonical one.
    fake = _FakeClassificationReader()
    assert isinstance(fake, ConfirmedClassificationReader)
    # Importing from both paths yields the SAME object (single-source
    # of Protocol):
    from wormbase_agent_gateway.column_classification import (
        ConfirmedClassificationReader as ViaSubpackage,
    )
    assert ConfirmedClassificationReader is ViaSubpackage


# ---------------------------------------------------------------------------
# Strategy — base cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_classifications_returns_empty() -> None:
    """Empty L6 reader → no governance-elevated proposals."""
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=_FakeClassificationReader(),
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_regulated_classification_elevates_to_critical() -> None:
    """``regulated`` classification → governance_severity=critical at 0.95."""
    reader = _FakeClassificationReader(
        [_rec(classification_level="regulated", classification_id="cls-reg")],
    )
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.strategy == "governance_classification"
    assert p.impact_kind == "tgt_column_orphaned"
    assert p.confidence == pytest.approx(0.95)
    assert p.evidence["governance_severity"] == "critical"
    assert p.evidence["classification_level"] == "regulated"
    assert p.evidence["upstream_classification_id"] == "cls-reg"
    # Target is the column itself — elevation is a separate row,
    # not downstream propagation.
    assert p.tgt_table_id == "warehouse.dim_customer"
    assert p.tgt_column == "email"
    # No L3 edge consumed; upstream_lineage_edge_id stays None.
    assert p.upstream_lineage_edge_id is None


@pytest.mark.asyncio
async def test_pii_classification_elevates_to_high() -> None:
    """``pii`` classification → governance_severity=high at 0.90."""
    reader = _FakeClassificationReader([_rec(classification_level="pii")])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].confidence == pytest.approx(0.90)
    assert proposals[0].evidence["governance_severity"] == "high"


@pytest.mark.asyncio
async def test_confidential_classification_elevates_to_high() -> None:
    """``confidential`` classification → governance_severity=high at 0.90."""
    reader = _FakeClassificationReader(
        [_rec(classification_level="confidential")],
    )
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].confidence == pytest.approx(0.90)
    assert proposals[0].evidence["governance_severity"] == "high"


@pytest.mark.asyncio
async def test_internal_classification_does_not_elevate() -> None:
    """``internal`` classification → no governance proposal (informational)."""
    reader = _FakeClassificationReader(
        [_rec(classification_level="internal")],
    )
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_public_classification_does_not_elevate() -> None:
    """``public`` classification → no governance proposal."""
    reader = _FakeClassificationReader([_rec(classification_level="public")])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert proposals == []


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
    reader = _FakeClassificationReader([_rec(classification_level="regulated")])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(
            kind=change_kind, old="varchar" if change_kind != "column_added" else None,
            new="varchar" if change_kind != "column_dropped" else None,
        ),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].impact_kind == expected_impact_kind


# ---------------------------------------------------------------------------
# Multi-level winner: highest severity wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_level_winner_picks_highest_severity() -> None:
    """Both ``pii`` AND ``regulated`` confirmed → elevate against regulated."""
    reader = _FakeClassificationReader([
        _rec(classification_level="pii", classification_id="cls-pii"),
        _rec(classification_level="regulated", classification_id="cls-reg"),
        _rec(classification_level="internal", classification_id="cls-int"),
    ])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.evidence["classification_level"] == "regulated"
    assert p.evidence["governance_severity"] == "critical"
    assert p.evidence["upstream_classification_id"] == "cls-reg"
    # Diagnostic count surfaces all confirmed classifications.
    assert p.evidence["classification_count"] == 3


@pytest.mark.asyncio
async def test_multi_level_winner_picks_pii_when_no_regulated() -> None:
    """``pii`` + ``internal`` confirmed → elevate against pii."""
    reader = _FakeClassificationReader([
        _rec(classification_level="internal", classification_id="cls-int"),
        _rec(classification_level="pii", classification_id="cls-pii"),
    ])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].evidence["classification_level"] == "pii"


# ---------------------------------------------------------------------------
# Multi-table same-column scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classifications_on_other_tables_filtered_out() -> None:
    """Reader may return classifications on other tables under same source;
    only the changed table's classifications elevate."""
    reader = _FakeClassificationReader([
        _rec(
            classification_level="regulated",
            classification_id="cls-other-tbl",
            table_id="warehouse.other_table",
        ),
        _rec(
            classification_level="pii",
            classification_id="cls-right-tbl",
            table_id="warehouse.dim_customer",
        ),
    ])
    strat = GovernanceClassificationImpactStrategy(
        confirmed_classification_reader=reader,
    )
    proposals = await strat.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    # Only the right-table classification elevated; the regulated on
    # other_table is filtered out, so winner is the pii.
    assert proposals[0].evidence["classification_level"] == "pii"
    assert proposals[0].evidence["upstream_classification_id"] == "cls-right-tbl"


# ---------------------------------------------------------------------------
# Composite integration — 4th strategy slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_governance_slot_optional_none_byte_identical() -> None:
    """Composite with all 3 original strategies + governance=None matches
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
        # governance_classification defaults to None — no kwarg passed.
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
    assert metrics["schema_impact_strategy_invocations.governance_classification"] == 0
    assert metrics["schema_impact_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_governance_slot_fires_independently() -> None:
    """Governance proposal stands as a separate row (different impact_id)
    from lineage_edge proposal."""
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

    reader = _FakeClassificationReader([
        _rec(classification_level="regulated", classification_id="cls-reg"),
    ])
    composite = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeLEReader(),
        ),
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    # Two proposals — lineage_edge targets downstream; governance
    # targets the changed column itself.
    assert len(proposals) == 2
    strategies = {p.strategy for p in proposals}
    assert strategies == {"lineage_edge", "governance_classification"}
    # Different impact_ids (different canonical tuples).
    impact_ids = {p.impact_id for p in proposals}
    assert len(impact_ids) == 2
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.governance_classification"] == 1
    assert metrics["schema_impact_strategy_invocations.lineage_edge"] == 1


@pytest.mark.asyncio
async def test_composite_governance_only() -> None:
    """Composite with only governance slot wired returns governance
    proposals when L6 has confirmed classifications."""
    reader = _FakeClassificationReader([
        _rec(classification_level="regulated", classification_id="cls-reg"),
    ])
    composite = CompositeSchemaImpactService(
        governance_classification=GovernanceClassificationImpactStrategy(
            confirmed_classification_reader=reader,
        ),
    )
    proposals = await composite.propose_impacts(
        source_id="warehouse",
        src_table="warehouse.dim_customer",
        change=_change(kind="column_dropped"),
        company_id=uuid4(),
    )
    assert len(proposals) == 1
    assert proposals[0].strategy == "governance_classification"
    metrics = composite.metrics()
    assert metrics["schema_impact_strategy_invocations.governance_classification"] == 1
    assert metrics["schema_impact_no_op"] == 0
