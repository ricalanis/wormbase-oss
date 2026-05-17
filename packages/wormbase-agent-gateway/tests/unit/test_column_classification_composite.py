"""L6 Sub-wave B — composite tests.

Pins the L6-specific wiring of the shared :class:`LakeLoopComposite`:

  * Factory returns a :class:`LakeLoopComposite` (not a custom class).
  * Optional-Effect Injection case 13: each slot independently
    ``None``-able; all-None yields ``[]`` + ``no_op`` counter.
  * Telemetry keys are axis-namespaced:
    ``column_classification_inference_*``.
  * Strategy slot order:
    ``semantic_type → naming_pattern → domain_default``.
  * Identity key = ``classification_id`` (which includes ``strategy``):
    two strategies proposing the SAME (table, column, level) produce
    DIFFERENT ids and stay separate rows (per spec §4.4 — diverges
    from L5's merge-on-(table,col,type)).
  * Second from-day-one consumer of LakeLoopComposite (after L5's first
    use).

Minimal — the generic shape is already pinned by
``test_lake_loop_composite.py`` and pre-extraction axes' suites.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.column_classification import (
    ConfirmedSemanticTypeRecord,
    DomainDefaultClassificationStrategy,
    NamingPatternClassificationStrategy,
    ProposedColumnClassification,
    SemanticTypeClassificationStrategy,
    make_classification_id,
    make_composite_column_classification_service,
)
from wormbase_agent_gateway.lake_loop import LakeLoopComposite


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0061")


class _FakeSemanticTypeReader:
    def __init__(
        self,
        types: dict[
            tuple[str, str], list[ConfirmedSemanticTypeRecord],
        ] | None = None,
    ) -> None:
        self.types = types or {}

    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        return self.types.get((table_id, column), [])


class _FakeDomainDefaultReader:
    def __init__(
        self,
        defaults: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self.defaults = defaults or {}

    async def get_classification_default_for_table(
        self, *, table_id, company_id,
    ):
        return self.defaults.get(table_id)


# ---------------------------------------------------------------------------
# Factory shape — validates LakeLoopComposite reuse (2nd from-day-one)
# ---------------------------------------------------------------------------


def test_factory_returns_lake_loop_composite_instance() -> None:
    """The smoking-gun validation: composite IS a :class:`LakeLoopComposite`.

    Pin: L6 does NOT define a custom composite class. The factory
    function delegates entirely to the shared generic. Second
    from-day-one consumer of the abstraction (after L5) — continues to
    validate that the DRY refactor at ``a4a62c2`` pays off for new
    consumers.
    """
    composite = make_composite_column_classification_service()
    assert isinstance(composite, LakeLoopComposite)


def test_factory_uses_column_classification_inference_case_name() -> None:
    """Composite's case_name is ``column_classification_inference``."""
    composite = make_composite_column_classification_service()
    assert composite.case_name == "column_classification_inference"


def test_factory_strategy_slots_match_spec() -> None:
    """Strategy slots are ``semantic_type`` / ``naming_pattern`` /
    ``domain_default`` in declaration order."""
    composite = make_composite_column_classification_service()
    slots = list(composite.strategies)
    assert slots == ["semantic_type", "naming_pattern", "domain_default"]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = make_composite_column_classification_service()
    proposals = await composite.propose(
        table_id="t", column="user_ssn", company_id=_COMPANY_ID,
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "column_classification_inference"
    assert metrics[f"{prefix}_invocations"] == 1
    assert metrics[f"{prefix}_no_op"] == 1
    assert metrics[f"{prefix}_classifications_proposed"] == 0
    assert metrics[f"{prefix}_strategy_invocations.semantic_type"] == 0
    assert metrics[f"{prefix}_strategy_invocations.naming_pattern"] == 0
    assert metrics[f"{prefix}_strategy_invocations.domain_default"] == 0


@pytest.mark.asyncio
async def test_composite_only_naming_pattern_runs() -> None:
    """``naming_pattern`` set, others None → only that counter increments."""
    composite = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    proposals = await composite.propose(
        table_id="t", column="user_ssn", company_id=_COMPANY_ID,
    )
    assert len(proposals) >= 1
    assert any(p.classification_level == "regulated" for p in proposals)
    metrics = composite.metrics()
    prefix = "column_classification_inference"
    assert metrics[f"{prefix}_strategy_invocations.naming_pattern"] == 1
    assert metrics[f"{prefix}_strategy_invocations.semantic_type"] == 0
    assert metrics[f"{prefix}_strategy_invocations.domain_default"] == 0
    assert metrics[f"{prefix}_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_two_strategies_same_level_keep_separate_rows() -> None:
    """Two strategies proposing the SAME (table, column, level) produce
    DIFFERENT classification_ids (per spec §4.4 — strategy is in the
    hash). Composite keeps them as separate rows; admin queue compares
    side-by-side.

    Diverges from L5 where same-(table, col, type) merges.
    """
    semantic_reader = _FakeSemanticTypeReader(types={
        ("t", "ssn"): [
            ConfirmedSemanticTypeRecord(
                type_id="upstream-ssn", semantic_type="pii_ssn",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    composite = make_composite_column_classification_service(
        semantic_type=SemanticTypeClassificationStrategy(
            semantic_type_reader=semantic_reader,
        ),
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    proposals = await composite.propose(
        table_id="t", column="ssn", company_id=_COMPANY_ID,
    )
    # Both strategies propose `regulated` for ssn — they stay separate.
    regulated = [p for p in proposals if p.classification_level == "regulated"]
    strategies = {p.strategy for p in regulated}
    assert "semantic_type" in strategies
    assert "naming_pattern" in strategies
    # Distinct classification_ids
    ids = {p.classification_id for p in regulated}
    assert len(ids) == len(regulated)


@pytest.mark.asyncio
async def test_composite_classification_id_is_canonical_hash() -> None:
    """Composite proposal's ``classification_id`` matches
    :func:`make_classification_id`."""
    composite = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    proposals = await composite.propose(
        table_id="t", column="user_password", company_id=_COMPANY_ID,
    )
    p = proposals[0]
    expected = make_classification_id(
        table_id="t", column="user_password",
        classification_level=p.classification_level, strategy="naming_pattern",
    )
    assert p.classification_id == expected


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_not_incremented() -> None:
    """Strategy wired but returns [] → no proposals, but no_op NOT fired.

    Per LakeLoopComposite contract: ``no_op`` reserved for the all-None
    Optional-Effect-absent path.
    """
    composite = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    # Column with no pattern match
    proposals = await composite.propose(
        table_id="t", column="random_unknown_thing", company_id=_COMPANY_ID,
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "column_classification_inference"
    assert metrics[f"{prefix}_strategy_invocations.naming_pattern"] == 1
    assert metrics[f"{prefix}_no_op"] == 0
    assert metrics[f"{prefix}_classifications_proposed"] == 0


@pytest.mark.asyncio
async def test_composite_returns_proposed_column_classification_instances() -> None:
    """Composite output is a list of :class:`ProposedColumnClassification`."""
    composite = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    out = await composite.propose(
        table_id="t", column="user_ssn", company_id=_COMPANY_ID,
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedColumnClassification) for p in out)


@pytest.mark.asyncio
async def test_composite_filters_below_min_confidence() -> None:
    """``min_confidence`` floor wired through factory → low-confidence
    proposals dropped; high-confidence survive; per-strategy telemetry
    intact (filter is post-merge, not per-strategy).

    Polish-bundle 2026-06-10. Pins the L6 wire-through of the shared
    LakeLoopComposite min_confidence floor — knob is sourced from
    ``WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE`` at the
    construction site.

    Test setup: SemanticTypeClassificationStrategy emits a proposal
    per confirmed semantic type. Two upstream types — one PII-SSN at
    0.95 confidence (high-stakes regulated) and one METRIC_COUNT at
    0.60 confidence (lower-stakes internal) — produce two proposals
    with distinct confidence floors. Setting the composite floor at
    0.90 keeps the regulated proposal and drops the metric proposal.
    """
    semantic_reader = _FakeSemanticTypeReader(types={
        ("t", "ssn"): [
            ConfirmedSemanticTypeRecord(
                type_id="upstream-ssn", semantic_type="pii_ssn",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("t", "metric_count_col"): [
            ConfirmedSemanticTypeRecord(
                type_id="upstream-mc", semantic_type="metric_count",
                confidence=0.60, strategy="column_name",
            ),
        ],
    })
    composite = make_composite_column_classification_service(
        semantic_type=SemanticTypeClassificationStrategy(
            semantic_type_reader=semantic_reader,
        ),
        min_confidence=0.90,
    )

    # High-confidence path (pii_ssn → regulated at 0.95): survives.
    hi_proposals = await composite.propose(
        table_id="t", column="ssn", company_id=_COMPANY_ID,
    )
    assert len(hi_proposals) == 1
    assert hi_proposals[0].confidence >= 0.90

    # Low-confidence path (metric_count → internal at 0.60): dropped.
    lo_proposals = await composite.propose(
        table_id="t", column="metric_count_col", company_id=_COMPANY_ID,
    )
    assert lo_proposals == []

    # Drop counter is auditable via metrics().
    metrics = composite.metrics()
    prefix = "column_classification_inference"
    assert metrics[f"{prefix}_below_min_confidence_dropped"] == 1
    # Per-strategy telemetry stays intact: semantic_type fired twice
    # and returned its full proposal set; the filter happens post-merge.
    assert metrics[f"{prefix}_strategy_invocations.semantic_type"] == 2


@pytest.mark.asyncio
async def test_composite_three_strategies_all_run() -> None:
    """All three slots wired → every strategy fires; proposals accumulated."""
    semantic_reader = _FakeSemanticTypeReader(types={
        ("t1", "ssn"): [
            ConfirmedSemanticTypeRecord(
                type_id="u-ssn", semantic_type="pii_ssn",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    domain_reader = _FakeDomainDefaultReader(
        defaults={"t1": ("internal", "default-pack")},
    )
    composite = make_composite_column_classification_service(
        semantic_type=SemanticTypeClassificationStrategy(
            semantic_type_reader=semantic_reader,
        ),
        naming_pattern=NamingPatternClassificationStrategy(),
        domain_default=DomainDefaultClassificationStrategy(
            domain_default_reader=domain_reader,
        ),
    )
    proposals = await composite.propose(
        table_id="t1", column="ssn", company_id=_COMPANY_ID,
    )
    strategies = {p.strategy for p in proposals}
    assert "semantic_type" in strategies
    assert "naming_pattern" in strategies
    assert "domain_default" in strategies
    metrics = composite.metrics()
    prefix = "column_classification_inference"
    assert metrics[f"{prefix}_strategy_invocations.semantic_type"] == 1
    assert metrics[f"{prefix}_strategy_invocations.naming_pattern"] == 1
    assert metrics[f"{prefix}_strategy_invocations.domain_default"] == 1
