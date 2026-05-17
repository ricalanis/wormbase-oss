"""L8 Sub-wave B — composite tests.

Pins the L8-specific wiring of the shared :class:`LakeLoopComposite`:

  * Factory returns a :class:`LakeLoopComposite` (not a custom class).
  * Optional-Effect Injection case 14: each slot independently
    ``None``-able; all-None yields ``[]`` + ``no_op`` counter.
  * Telemetry keys are axis-namespaced: ``entity_stitch_inference_*``.
  * Strategy slot order:
    ``name_match → sample_overlap → schema_shape``.
  * Identity key = ``stitch_id`` (order-independent; OMITS strategy):
    two strategies proposing the SAME pair (in either order) collide
    and merge (per spec §4.4; mirrors L5, diverges from L6's
    keep-separate-by-strategy).
  * Third from-day-one consumer of LakeLoopComposite (after L5 + L6).

Minimal — the generic shape is already pinned by
``test_lake_loop_composite.py`` and pre-extraction axes' suites.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.column_classification import (
    ConfirmedSemanticTypeRecord,
)
from wormbase_agent_gateway.entity_stitch import (
    NameMatchEntityStrategy,
    ProposedEntityStitch,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
    make_composite_entity_stitch_service,
)
from wormbase_agent_gateway.lake_loop import LakeLoopComposite


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0091")


class _FakeSemanticTypeReader:
    def __init__(self, types=None):
        self.types = types or {}

    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        return self.types.get((table_id, column), [])


class _FakeSampler:
    def __init__(self, samples=None):
        self.samples = samples or {}

    async def sample_column(self, table_id, column, n):
        return self.samples.get((table_id, column), set())

    async def estimate_table_size(self, table_id):
        return 0


# ---------------------------------------------------------------------------
# Factory shape — validates LakeLoopComposite reuse (3rd from-day-one)
# ---------------------------------------------------------------------------


def test_factory_returns_lake_loop_composite_instance() -> None:
    """The smoking-gun validation: composite IS a :class:`LakeLoopComposite`.

    Pin: L8 does NOT define a custom composite class. The factory
    function delegates entirely to the shared generic. **Third**
    from-day-one consumer of the abstraction (after L5 + L6) — continues
    to validate that the DRY refactor at ``a4a62c2`` pays off for new
    consumers.
    """
    composite = make_composite_entity_stitch_service()
    assert isinstance(composite, LakeLoopComposite)


def test_factory_uses_entity_stitch_inference_case_name() -> None:
    """Composite's case_name is ``entity_stitch_inference``."""
    composite = make_composite_entity_stitch_service()
    assert composite.case_name == "entity_stitch_inference"


def test_factory_strategy_slots_match_spec() -> None:
    """Strategy slots are ``name_match`` / ``sample_overlap`` /
    ``schema_shape`` in declaration order."""
    composite = make_composite_entity_stitch_service()
    slots = list(composite.strategies)
    assert slots == ["name_match", "sample_overlap", "schema_shape"]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = make_composite_entity_stitch_service()
    proposals = await composite.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "x"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "y"},
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "entity_stitch_inference"
    assert metrics[f"{prefix}_invocations"] == 1
    assert metrics[f"{prefix}_no_op"] == 1
    assert metrics[f"{prefix}_stitches_proposed"] == 0
    assert metrics[f"{prefix}_strategy_invocations.name_match"] == 0
    assert metrics[f"{prefix}_strategy_invocations.sample_overlap"] == 0
    assert metrics[f"{prefix}_strategy_invocations.schema_shape"] == 0


@pytest.mark.asyncio
async def test_composite_only_name_match_runs() -> None:
    """``name_match`` set, others None → only that counter increments."""
    composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
    )
    # Fuzzy-name path will fire on similar-looking column names
    proposals = await composite.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email",
        },
    )
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "entity_stitch_inference"
    assert metrics[f"{prefix}_strategy_invocations.name_match"] == 1
    assert metrics[f"{prefix}_strategy_invocations.sample_overlap"] == 0
    assert metrics[f"{prefix}_strategy_invocations.schema_shape"] == 0
    assert metrics[f"{prefix}_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_two_strategies_merge_on_same_stitch_id() -> None:
    """NameMatch (anchor) + SampleOverlap proposing the SAME pair → composite
    merges into ONE row.

    Diverges from L6 (which keeps strategies separate); mirrors L5's
    merge-on-(table,col,type). Per spec §4.4.
    """
    samples = {"a@x.com", "b@x.com"}
    sampler = _FakeSampler(samples={
        ("stripe.customers", "email"): samples,
        ("salesforce.contacts", "email"): samples,
    })
    reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t1", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("salesforce.contacts", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t2", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=reader,
        ),
        sample_overlap=SampleOverlapEntityStrategy(sampler=sampler),
    )
    proposals = await composite.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email",
        },
    )
    # All proposals on the SAME pair → same stitch_id → merged into one row
    ids = {p.stitch_id for p in proposals}
    assert len(ids) == 1
    # The merged row has strategy="composite" + accumulated reasoning
    merged = proposals[0]
    assert merged.strategy == "composite"


@pytest.mark.asyncio
async def test_composite_filters_below_min_confidence() -> None:
    """``min_confidence`` floor wired through factory → low-confidence
    proposals dropped; high-confidence survive; per-strategy telemetry
    intact (filter is post-merge, not per-strategy).

    Polish-bundle 2026-06-10. Pins the L8 wire-through of the shared
    LakeLoopComposite min_confidence floor — knob is sourced from
    ``WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE`` at the construction
    site.

    Test setup: NameMatch with a confirmed semantic-type anchor on
    both endpoints fires at SEMANTIC_TYPE_CONFIDENCE (0.90).
    NameMatch with NO confirmed semantic type fires at fuzzy-name
    confidence (0.50-0.85). Setting the composite floor at 0.88
    keeps the anchored proposal and drops the fuzzy one.
    """
    # Anchored: both endpoints share a confirmed pii_email type.
    anchored_reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t1", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("salesforce.contacts", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t2", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })

    # Fuzzy-only: no semantic-type anchors.
    fuzzy_reader = _FakeSemanticTypeReader()

    # Anchored composite — high-confidence proposal survives 0.88 floor.
    anchored_composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=anchored_reader,
        ),
        min_confidence=0.88,
    )
    anchored_proposals = await anchored_composite.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email",
        },
    )
    assert len(anchored_proposals) >= 1
    assert all(p.confidence >= 0.88 for p in anchored_proposals)
    anchored_metrics = anchored_composite.metrics()
    prefix = "entity_stitch_inference"
    assert anchored_metrics[f"{prefix}_below_min_confidence_dropped"] == 0

    # Fuzzy-only composite — low-confidence (fuzzy <0.88) drops.
    fuzzy_composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=fuzzy_reader,
        ),
        min_confidence=0.88,
    )
    fuzzy_proposals = await fuzzy_composite.propose(
        company_id=_COMPANY_ID,
        column_a={
            "source_id": "stripe", "table_id": "stripe.customers",
            "column": "email",
        },
        column_b={
            "source_id": "salesforce", "table_id": "salesforce.contacts",
            "column": "email",
        },
    )
    # Fuzzy max is 0.85; floor 0.88 → all proposals drop.
    assert fuzzy_proposals == []
    fuzzy_metrics = fuzzy_composite.metrics()
    assert fuzzy_metrics[f"{prefix}_below_min_confidence_dropped"] >= 1
    # Per-strategy telemetry stays intact: name_match fired and
    # returned its full proposal set; the filter happens post-merge.
    assert fuzzy_metrics[f"{prefix}_strategy_invocations.name_match"] == 1


@pytest.mark.asyncio
async def test_composite_returns_proposed_entity_stitch_instances() -> None:
    """Composite output is a list of :class:`ProposedEntityStitch`."""
    composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
    )
    out = await composite.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "email"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "email"},
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedEntityStitch) for p in out)


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_not_incremented() -> None:
    """Strategy wired but returns [] → no proposals, but no_op NOT fired."""
    composite = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
    )
    # Wildly different column names → fuzzy path no-match; no anchor types
    proposals = await composite.propose(
        company_id=_COMPANY_ID,
        column_a={"source_id": "a", "table_id": "a.t", "column": "totally_xyz"},
        column_b={"source_id": "b", "table_id": "b.t", "column": "completely_abc"},
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "entity_stitch_inference"
    assert metrics[f"{prefix}_strategy_invocations.name_match"] == 1
    assert metrics[f"{prefix}_no_op"] == 0
    assert metrics[f"{prefix}_stitches_proposed"] == 0
