"""L1 Sub-wave B — composite tests.

Pins the L1-specific wiring of the shared :class:`LakeLoopComposite`:

  * Factory returns a :class:`LakeLoopComposite` (NOT a custom class).
  * Optional-Effect Injection case 15: each slot independently
    ``None``-able; all-None yields ``[]`` + ``no_op`` counter.
  * Telemetry keys are axis-namespaced: ``source_candidate_inference_*``.
  * Strategy slot order:
    ``kpi_gap → channel_mention → complementarity``.
  * Identity key = ``candidate_id`` (INCLUDES strategy in hash):
    different strategies proposing the same (kind, identifier) yield
    DISTINCT rows (kept-separate-by-strategy; mirrors L6, diverges
    from L5/L8).
  * Fourth from-day-one consumer of LakeLoopComposite (after L5 + L6 + L8).

Minimal — the generic shape is already pinned by
``tests/unit/test_lake_loop_composite.py`` and the pre-extraction axes'
suites.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.lake_loop import LakeLoopComposite
from wormbase_agent_gateway.source_candidates import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    ConnectedSourceRecord,
    KpiGapAcquisitionStrategy,
    KpiNodeRecord,
    ProposedSourceCandidate,
    SilverConversationRecord,
    make_composite_source_candidate_service,
)


_COMPANY = UUID("00000000-0000-0000-0000-000000000a04")


class _FakeKpiNodeReader:
    def __init__(self, nodes=None):
        self.nodes = nodes or []

    async def list_kpi_nodes_without_source(self, *, company_id):
        return list(self.nodes)


class _FakeSilverConversationReader:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def list_recent_conversations(self, *, company_id, since_seconds=86400):
        return list(self.rows)


class _FakeConnectedSourceReader:
    def __init__(self, sources=None):
        self.sources = sources or []

    async def list_connected_sources(self, *, company_id):
        return list(self.sources)


# ---------------------------------------------------------------------------
# Factory shape — validates LakeLoopComposite reuse (4th from-day-one)
# ---------------------------------------------------------------------------


def test_factory_returns_lake_loop_composite_instance() -> None:
    """The smoking-gun validation: composite IS a :class:`LakeLoopComposite`.

    Pin: L1 does NOT define a custom composite class. The factory
    function delegates entirely to the shared generic. **Fourth**
    from-day-one consumer of the abstraction (after L5 + L6 + L8) —
    continues to validate that the DRY refactor at ``a4a62c2`` pays
    off for new consumers.
    """
    composite = make_composite_source_candidate_service()
    assert isinstance(composite, LakeLoopComposite)


def test_factory_uses_source_candidate_inference_case_name() -> None:
    """Composite's case_name is ``source_candidate_inference``."""
    composite = make_composite_source_candidate_service()
    assert composite.case_name == "source_candidate_inference"


def test_factory_strategy_slots_match_spec() -> None:
    """Slots are ``kpi_gap`` / ``channel_mention`` / ``complementarity`` in order."""
    composite = make_composite_source_candidate_service()
    slots = list(composite.strategies)
    assert slots == ["kpi_gap", "channel_mention", "complementarity"]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = make_composite_source_candidate_service()
    proposals = await composite.propose(company_id=_COMPANY)
    assert proposals == []
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_invocations"] == 1
    assert metrics[f"{prefix}_no_op"] == 1
    assert metrics[f"{prefix}_source_candidates_proposed"] == 0
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 0
    assert metrics[f"{prefix}_strategy_invocations.channel_mention"] == 0
    assert metrics[f"{prefix}_strategy_invocations.complementarity"] == 0


@pytest.mark.asyncio
async def test_composite_only_kpi_gap_runs() -> None:
    """``kpi_gap`` set, others None → only that counter increments."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id="dom-fin"),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=reader),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 1
    assert metrics[f"{prefix}_strategy_invocations.channel_mention"] == 0
    assert metrics[f"{prefix}_strategy_invocations.complementarity"] == 0
    assert metrics[f"{prefix}_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_only_channel_mention_runs() -> None:
    """``channel_mention`` set, others None → only that counter increments."""
    reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id=None, classification="public",
        ),
    ])
    composite = make_composite_source_candidate_service(
        channel_mention=ChannelMentionAcquisitionStrategy(
            silver_conversation_reader=reader,
        ),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_strategy_invocations.channel_mention"] == 1
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 0


@pytest.mark.asyncio
async def test_composite_only_complementarity_runs() -> None:
    """``complementarity`` set, others None → only that counter increments."""
    reader = _FakeConnectedSourceReader([
        ConnectedSourceRecord("s-1", "stripe", "sales", "internal"),
        ConnectedSourceRecord("s-2", "salesforce", "sales", "internal"),
    ])
    composite = make_composite_source_candidate_service(
        complementarity=ComplementaritySourceStrategy(
            connected_source_reader=reader,
        ),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_strategy_invocations.complementarity"] == 1
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 0


# ---------------------------------------------------------------------------
# Strategy returns empty but slot is wired — no_op should NOT increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_not_incremented() -> None:
    """Strategy wired but returns [] → no proposals, but no_op NOT fired."""
    # Empty reader → KpiGap returns []
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader()),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    assert proposals == []
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 1
    # no_op only fires when EVERY slot is None — here kpi_gap is wired.
    assert metrics[f"{prefix}_no_op"] == 0
    assert metrics[f"{prefix}_source_candidates_proposed"] == 0


# ---------------------------------------------------------------------------
# Kept-separate-by-strategy (identity key includes strategy)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_distinct_strategies_propose_same_kind_stay_separate() -> None:
    """Two strategies proposing the same connector kind → DISTINCT rows.

    Pin: candidate_id hash INCLUDES strategy (mirrors L6, diverges from
    L5/L8 merge-on-pair). Spec §4.7.
    """
    # KpiGap proposes stripe for a revenue KPI;
    # ChannelMention proposes stripe for a "stripe" mention.
    kpi_reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id=None),
    ])
    silver_reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="export from stripe",
            domain_id=None, classification="public",
        ),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=kpi_reader),
        channel_mention=ChannelMentionAcquisitionStrategy(
            silver_conversation_reader=silver_reader,
        ),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    stripe_props = [p for p in proposals if p.proposed_kind == "stripe"]
    # Two distinct proposals — one per strategy
    assert len(stripe_props) == 2
    strategies = {p.strategy for p in stripe_props}
    assert strategies == {"kpi_gap", "channel_mention"}
    # And the candidate_ids differ (hash includes strategy)
    ids = {p.candidate_id for p in stripe_props}
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_composite_returns_proposed_source_candidate_instances() -> None:
    """Composite output is a list of :class:`ProposedSourceCandidate`."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id=None),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=reader),
    )
    out = await composite.propose(company_id=_COMPANY)
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedSourceCandidate) for p in out)


@pytest.mark.asyncio
async def test_composite_filters_below_min_confidence() -> None:
    """``min_confidence`` floor wired through factory → low-confidence
    proposals dropped; high-confidence survive; per-strategy telemetry
    intact (filter is post-merge, not per-strategy).

    Polish-bundle 2026-06-10. Pins the L1 wire-through of the shared
    LakeLoopComposite min_confidence floor — knob is sourced from
    ``WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE`` (L1 default 0.4 per
    spec §4.8) at the construction site.

    Test setup: KpiGap maps a "revenue" KPI to stripe at 0.80
    confidence (pattern-match high tier), and any unmatched KPI to
    csv_local at the fallback confidence 0.40. Setting the floor at
    0.70 keeps the revenue proposal and drops the fallback proposal.
    """
    kpi_reader = _FakeKpiNodeReader([
        KpiNodeRecord(
            kpi_node_id="k-1", name="q3_revenue", domain_id="dom-fin",
        ),
        KpiNodeRecord(
            kpi_node_id="k-2", name="zzz_obscure_kpi", domain_id="dom-fin",
        ),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=kpi_reader),
        min_confidence=0.70,
    )
    proposals = await composite.propose(company_id=_COMPANY)
    # All surviving proposals must clear the floor.
    assert all(p.confidence >= 0.70 for p in proposals)
    # At least one survives — revenue → stripe at 0.80.
    assert any(p.proposed_kind == "stripe" for p in proposals)
    # csv_local fallback (0.40) should be dropped.
    assert not any(
        p.proposed_kind == "csv_local" and p.confidence < 0.70
        for p in proposals
    )
    # Drop counter is auditable via metrics().
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_below_min_confidence_dropped"] >= 1
    # Per-strategy telemetry stays intact: kpi_gap fired once and
    # returned its full proposal set; the filter happens post-merge.
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 1


@pytest.mark.asyncio
async def test_composite_telemetry_aggregates_across_invocations() -> None:
    """Counters accumulate across multiple ``propose`` calls."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id=None),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=reader),
    )
    await composite.propose(company_id=_COMPANY)
    await composite.propose(company_id=_COMPANY)
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_invocations"] == 2
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 2
    assert metrics[f"{prefix}_source_candidates_proposed"] == 2


@pytest.mark.asyncio
async def test_composite_all_three_strategies_run() -> None:
    """All 3 strategies wired → all 3 counter slots increment per call."""
    kpi_reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id=None),
    ])
    silver_reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-1",
            text="our snowflake warehouse",
            domain_id=None, classification="public",
        ),
    ])
    src_reader = _FakeConnectedSourceReader([
        ConnectedSourceRecord("s-1", "stripe", "sales", "internal"),
        ConnectedSourceRecord("s-2", "salesforce", "sales", "internal"),
    ])
    composite = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=kpi_reader),
        channel_mention=ChannelMentionAcquisitionStrategy(
            silver_conversation_reader=silver_reader,
        ),
        complementarity=ComplementaritySourceStrategy(
            connected_source_reader=src_reader,
        ),
    )
    proposals = await composite.propose(company_id=_COMPANY)
    metrics = composite.metrics()
    prefix = "source_candidate_inference"
    assert metrics[f"{prefix}_strategy_invocations.kpi_gap"] == 1
    assert metrics[f"{prefix}_strategy_invocations.channel_mention"] == 1
    assert metrics[f"{prefix}_strategy_invocations.complementarity"] == 1
    assert metrics[f"{prefix}_no_op"] == 0
    # At least one proposal each from kpi_gap (stripe) + channel_mention (snowflake)
    # + complementarity (hubspot) — verifies all 3 paths actually emit
    kinds = {p.proposed_kind for p in proposals}
    assert "stripe" in kinds
    assert "snowflake" in kinds
    assert "hubspot" in kinds
