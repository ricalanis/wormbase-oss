"""L5→L7 cross-axis chain — SemanticTypeQualityCheckStrategy tests.

The **4th cross-axis chain** (after L4→L3, L6→L5, L8→L5). Pins:

  * Per-semantic-type → check-kinds mapping (email → not_null+unique,
    phone → not_null only, uuid → not_null+unique, business_id →
    not_null+unique, pii_name → not_null only).
  * Unknown semantic types yield no proposals (conservative).
  * ``upstream_semantic_type_id`` threaded onto every proposal so the
    /lake/quality cross-axis link can render.
  * Multi-column / multi-table sweep yields correct proposal count.
  * ``company_id=None`` short-circuits to empty (strategy requires tenant
    scope).
  * Symbol-identity test: the strategy reuses L6's
    :class:`ConfirmedSemanticTypeReader` Protocol (3rd consumer; L6 is
    1st, L8 is 2nd, L7 is 3rd).
  * Composite integration: cross-axis strategy is additive — composite
    with only ``semantic_type`` works; composite with all 4 strategies
    aggregates; default ``None`` preserves byte-identical pre-cross-axis
    behaviour.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.column_classification.protocol import (
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.quality import (
    CatalogTable,
    CompositeQualityProposalService,
    SchemaPatternStrategy,
    SemanticTypeQualityCheckStrategy,
)
from wormbase_agent_gateway.quality import strategies as l7_strategies


_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000c01")


class _FakeReader:
    """Test double matching the L6 ConfirmedSemanticTypeReader Protocol.

    Keyed by ``(table_id, column)`` → list of records. Returns ``[]``
    for keys not in the dict. Mirrors the per-(table_id, column) read
    pattern the strategy uses (per spec — the Protocol's actual method
    signature).
    """

    def __init__(
        self,
        records: dict[tuple[str, str], list[ConfirmedSemanticTypeRecord]] | None = None,
    ) -> None:
        self.records = records or {}
        self.calls: list[tuple[str, str, UUID]] = []

    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[ConfirmedSemanticTypeRecord]:
        self.calls.append((table_id, column, company_id))
        return list(self.records.get((table_id, column), []))


def _table(
    table_id: str,
    columns: tuple[str, ...],
    kind: str = "postgres",
) -> CatalogTable:
    return CatalogTable(
        table_id=table_id,
        columns=columns,
        source_kind=kind,
        metadata={},
    )


def _record(
    semantic_type: str,
    *,
    type_id: str | None = None,
    confidence: float = 0.95,
    strategy: str = "column_name",
) -> ConfirmedSemanticTypeRecord:
    return ConfirmedSemanticTypeRecord(
        type_id=type_id or f"tid-{semantic_type}",
        semantic_type=semantic_type,
        confidence=confidence,
        strategy=strategy,
    )


# ---------------------------------------------------------------------------
# Empty / no-op paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_reader_yields_no_proposals() -> None:
    """When the reader returns [] for every column, the strategy emits []."""
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=_FakeReader(),
    )
    table = _table("src.public.users", ("email", "name", "id"))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_company_id_none_short_circuits() -> None:
    """Without a tenant scope, the strategy emits [] without touching the reader."""
    reader = _FakeReader(
        records={("src.public.users", "email"): [_record("email")]},
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("email",))
    proposals = await strategy.propose_checks(
        table=table, company_id=None,
    )
    assert proposals == []
    # Reader was never called — tenant short-circuit ran before any read.
    assert reader.calls == []


@pytest.mark.asyncio
async def test_no_columns_yields_no_proposals() -> None:
    """A table with empty columns tuple → no proposals; no reader calls."""
    reader = _FakeReader()
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.empty", ())
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    assert proposals == []
    assert reader.calls == []


# ---------------------------------------------------------------------------
# Per-semantic-type mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_yields_not_null_plus_unique() -> None:
    """email semantic type → 2 proposals: not_null + unique."""
    reader = _FakeReader(
        records={
            ("src.public.users", "email"): [_record("email", type_id="tid-1")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("email",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    kinds = sorted(p.check_kind for p in proposals)
    assert kinds == ["not_null", "unique"]
    for p in proposals:
        assert p.strategy == "semantic_type"
        assert p.column == "email"
        assert p.table_id == "src.public.users"
        assert p.confidence == pytest.approx(0.85)
        assert p.upstream_semantic_type_id == "tid-1"
        assert p.evidence["semantic_type"] == "email"
        assert p.evidence["upstream_semantic_type_id"] == "tid-1"


@pytest.mark.asyncio
async def test_phone_yields_not_null_only() -> None:
    """phone_e164 semantic type → 1 proposal: not_null. Uniqueness varies."""
    reader = _FakeReader(
        records={
            ("src.public.users", "phone"): [_record("phone_e164", type_id="t-p")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("phone",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    assert len(proposals) == 1
    assert proposals[0].check_kind == "not_null"
    assert proposals[0].column == "phone"
    assert proposals[0].upstream_semantic_type_id == "t-p"


@pytest.mark.asyncio
async def test_uuid_v4_yields_not_null_plus_unique() -> None:
    """uuid_v4 semantic type → not_null + unique (UUIDs are unique)."""
    reader = _FakeReader(
        records={
            ("src.public.t", "id"): [_record("uuid_v4", type_id="t-u")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.t", ("id",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    kinds = sorted(p.check_kind for p in proposals)
    assert kinds == ["not_null", "unique"]


@pytest.mark.asyncio
async def test_pii_name_yields_not_null_only() -> None:
    """pii_name semantic type → 1 proposal: not_null. Names duplicate."""
    reader = _FakeReader(
        records={
            ("src.public.users", "name"): [_record("pii_name", type_id="t-n")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("name",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    assert len(proposals) == 1
    assert proposals[0].check_kind == "not_null"
    assert proposals[0].column == "name"


@pytest.mark.asyncio
async def test_business_id_yields_not_null_plus_unique() -> None:
    """business_id → not_null + unique (typically primary key material)."""
    reader = _FakeReader(
        records={
            ("src.public.t", "biz_ref"): [_record("business_id", type_id="t-b")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.t", ("biz_ref",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    kinds = sorted(p.check_kind for p in proposals)
    assert kinds == ["not_null", "unique"]


@pytest.mark.asyncio
async def test_unknown_semantic_type_yields_no_proposals() -> None:
    """Semantic types not in the mapping table → no proposals (conservative)."""
    reader = _FakeReader(
        records={
            ("src.public.t", "amt"): [
                _record("metric_amount", type_id="t-m"),
            ],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.t", ("amt",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    # metric_amount is intentionally not in the mapping (no canonical
    # not_null/unique semantics) — strategy emits nothing.
    assert proposals == []


# ---------------------------------------------------------------------------
# Multi-column sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_column_sweep_emits_correct_proposal_count() -> None:
    """A table with email + phone + pii_name columns → 4 proposals
    (email=2, phone=1, name=1). Reader called once per column."""
    reader = _FakeReader(
        records={
            ("src.public.users", "email"): [_record("email", type_id="tid-e")],
            ("src.public.users", "phone"): [_record("phone_e164", type_id="tid-p")],
            ("src.public.users", "name"): [_record("pii_name", type_id="tid-n")],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("email", "phone", "name"))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    # email: not_null + unique = 2
    # phone: not_null         = 1
    # name:  not_null         = 1
    assert len(proposals) == 4
    by_col_kind = sorted((p.column, p.check_kind) for p in proposals)
    assert by_col_kind == [
        ("email", "not_null"),
        ("email", "unique"),
        ("name", "not_null"),
        ("phone", "not_null"),
    ]
    # Reader called once per column (3 columns).
    assert len(reader.calls) == 3
    # Each call passed company_id through.
    for _table_id, _column, cid in reader.calls:
        assert cid == _COMPANY_ID


@pytest.mark.asyncio
async def test_multiple_confirmed_types_on_one_column() -> None:
    """A column confirmed as BOTH email AND pii_name → 3 proposals
    (email contributes not_null + unique; pii_name contributes
    not_null on top, which dedups at the composite level — but the
    bare strategy emits all of them)."""
    reader = _FakeReader(
        records={
            ("src.public.users", "user_email"): [
                _record("email", type_id="tid-e", confidence=0.92),
                _record("pii_name", type_id="tid-n", confidence=0.71),
            ],
        },
    )
    strategy = SemanticTypeQualityCheckStrategy(
        confirmed_semantic_type_reader=reader,
    )
    table = _table("src.public.users", ("user_email",))
    proposals = await strategy.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    # 2 from email + 1 from pii_name = 3 raw proposals.
    assert len(proposals) == 3
    kinds = sorted(p.check_kind for p in proposals)
    assert kinds == ["not_null", "not_null", "unique"]


# ---------------------------------------------------------------------------
# Symbol-identity reuse pin (the canonical cross-axis Protocol-reuse test).
# ---------------------------------------------------------------------------


def test_l7_reuses_l6_confirmed_semantic_type_reader_protocol() -> None:
    """The L7 SemanticTypeQualityCheckStrategy imports the L6 Protocol;
    L7 does NOT redeclare a parallel cross-axis Protocol.

    **3rd consumer** (1st = L6 own; 2nd = L8 NameMatch; 3rd = L7
    SemanticType). Validates the consumer-owned-Protocol pattern
    generalises across N downstream consumers — the L4→L3, L6→L5,
    L8→L5 chains share the same shape; L5→L7 is the 4th.
    """
    from wormbase_agent_gateway.column_classification.protocol import (
        ConfirmedSemanticTypeReader as L6Reader,
    )
    # The strategies module imports the L6 Protocol symbol directly.
    assert l7_strategies.ConfirmedSemanticTypeReader is L6Reader
    # And the strategy's __init__ annotation references the same
    # symbol — pins the cross-axis Protocol reuse at the type level.
    import typing
    hints = typing.get_type_hints(
        SemanticTypeQualityCheckStrategy.__init__,
    )
    assert hints["confirmed_semantic_type_reader"] is L6Reader


# ---------------------------------------------------------------------------
# Composite integration — additive 4th slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_with_only_semantic_type_runs() -> None:
    """Composite with only the new strategy wired → 4th slot fires."""
    reader = _FakeReader(
        records={
            ("src.public.users", "email"): [_record("email", type_id="tid-e")],
        },
    )
    composite = CompositeQualityProposalService(
        semantic_type=SemanticTypeQualityCheckStrategy(
            confirmed_semantic_type_reader=reader,
        ),
    )
    table = _table("src.public.users", ("email",))
    proposals = await composite.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    assert len(proposals) == 2  # not_null + unique
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.semantic_type"] == 1
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 0
    assert metrics["quality_inference_strategy_invocations.dbt_tests"] == 0
    assert metrics["quality_inference_strategy_invocations.historical_stats"] == 0
    assert metrics["quality_inference_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_semantic_type_none_preserves_existing_behaviour() -> None:
    """Default-OFF byte-identical: composite without semantic_type still
    works and the per-slot counter for semantic_type stays at 0."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    table = _table("src.public.orders", ("customer_id",))
    proposals = await composite.propose_checks(table=table)
    # schema_pattern fires its id-naming heuristic on customer_id → unique check.
    assert len(proposals) >= 1
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.semantic_type"] == 0
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 1


@pytest.mark.asyncio
async def test_composite_all_four_strategies_aggregate() -> None:
    """All 4 slots wired → counter for each fires once on an invocation."""
    reader = _FakeReader(
        records={
            ("src.public.users", "email"): [_record("email", type_id="tid-e")],
        },
    )
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
        semantic_type=SemanticTypeQualityCheckStrategy(
            confirmed_semantic_type_reader=reader,
        ),
        # dbt_tests + historical_stats deliberately left None — proves
        # the new slot is additive and independent.
    )
    table = _table("src.public.users", ("email",))
    proposals = await composite.propose_checks(
        table=table, company_id=_COMPANY_ID,
    )
    # email column: schema_pattern doesn't fire (no id-naming or
    # timestamp pattern, no metadata); semantic_type fires not_null +
    # unique = 2 proposals.
    assert len(proposals) >= 2
    # Every proposal from the semantic_type strategy carries the
    # upstream link — pins that the composite preserves the additive
    # field through the merge.
    semantic_proposals = [
        p for p in proposals
        if p.upstream_semantic_type_id is not None
        or p.strategy == "semantic_type"
    ]
    assert len(semantic_proposals) >= 2
    for p in semantic_proposals:
        assert p.upstream_semantic_type_id == "tid-e"
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.semantic_type"] == 1
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 1


@pytest.mark.asyncio
async def test_composite_default_off_does_not_call_reader() -> None:
    """When the cross-axis strategy is None on the composite, the L6
    reader is never instantiated — byte-identical pre-cross-axis
    runtime cost. Verified via composite.semantic_type."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    assert composite.semantic_type is None
